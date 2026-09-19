"""CDK stack for the storefront's identity: the Cognito User Pool storefront customers sign
into, its app client, the "admin" group, and the post-confirmation trigger Lambda. Split out
from StorefrontStack so redeploying the API/Lambda code never touches identity infrastructure
— the User Pool is retained on stack teardown and is the one piece of this app that must
outlive routine redeploys.

StorefrontStack imports this stack's `user_pool` / `user_pool_client` to build its Cognito
HTTP API authorizer (see app.py for the wiring order).

The post-confirmation trigger provisions a local `users` row via Postgres (see
storefront/handlers/common/cognito_trigger.py), so it needs the same VPC/DB access as
StorefrontStack's Lambdas — this stack takes `vpc`/`db_security_group` from NetworkStack and
the same `-c dbSecretArn=... -c dbHost=... -c dbName=...` context values StorefrontStack
requires (see that stack's docstring for why host/dbname are separate, plain context values
rather than part of the secret).
"""
from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct
from lambda_assets import (
    LAMBDA_RUNTIME,
    build_dependencies_layer,
    build_storefront_code,
    parse_handler,
)

COGNITO_TRIGGER_HANDLER = "storefront/handlers/common/cognito_trigger.lambda_handler"


class CognitoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc,
                 db_security_group: ec2.ISecurityGroup, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self, "StorefrontUserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_uppercase=False,
                require_digits=True, require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            # A stack teardown/redeploy must never delete real users.
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.user_pool_client = self.user_pool.add_client(
            "StorefrontAppClient",
            generate_secret=False,  # public/SPA client — the site calls Cognito directly
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
        )
        cognito.CfnUserPoolGroup(
            self, "AdminGroup", user_pool_id=self.user_pool.user_pool_id, group_name="admin",
        )

        db_secret_arn = self.node.try_get_context("dbSecretArn")
        db_host = self.node.try_get_context("dbHost")
        db_name = self.node.try_get_context("dbName")
        if not (db_secret_arn and db_host and db_name):
            raise ValueError(
                "CognitoStack requires -c dbSecretArn=... -c dbHost=... -c dbName=... "
                "(see this file's module docstring)"
            )
        db_secret = secretsmanager.Secret.from_secret_complete_arn(self, "DbSecret", db_secret_arn)

        # Scoped here rather than as an ingress rule on db_security_group's own stack
        # (NetworkStack) for the same one-directional-dependency reason as StorefrontStack's
        # identical pattern (see that stack's `_build_function`/ingress-rule comment).
        lambda_security_group = ec2.SecurityGroup(
            self, "CognitoTriggerLambdaSg", vpc=vpc,
            description="Cognito post-confirmation trigger Lambda to Postgres",
            allow_all_outbound=True,
        )
        ec2.CfnSecurityGroupIngress(
            self, "RdsIngressFromCognitoTrigger",
            ip_protocol="tcp", from_port=5432, to_port=5432,
            group_id=db_security_group.security_group_id,
            source_security_group_id=lambda_security_group.security_group_id,
            description="Cognito post-confirmation trigger Lambda to Postgres",
        )

        post_confirmation = _lambda.Function(
            self, "CognitoPostConfirmation",
            code=build_storefront_code(),
            handler=parse_handler(COGNITO_TRIGGER_HANDLER),
            runtime=LAMBDA_RUNTIME,
            layers=[build_dependencies_layer(self)],
            timeout=Duration.seconds(10),
            vpc=vpc,
            security_groups=[lambda_security_group],
            environment={
                "DB_SECRET_ARN": db_secret.secret_arn,
                "DB_HOST": db_host,
                "DB_NAME": db_name,
            },
        )
        db_secret.grant_read(post_confirmation)
        self.user_pool.add_trigger(cognito.UserPoolOperation.POST_CONFIRMATION, post_confirmation)
