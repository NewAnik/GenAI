"""CDK stack for the storefront's identity: the Cognito User Pool storefront customers sign
into, its app client, the "admin" group, and the post-confirmation trigger Lambda. Split out
from StorefrontStack so redeploying the API/Lambda code never touches identity infrastructure
— the User Pool is retained on stack teardown and is the one piece of this app that must
outlive routine redeploys.

StorefrontStack imports this stack's `user_pool` / `user_pool_client` to build its Cognito
HTTP API authorizer (see app.py for the wiring order).
"""
from __future__ import annotations

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as _lambda
from constructs import Construct
from lambda_assets import (
    LAMBDA_RUNTIME,
    build_dependencies_layer,
    build_storefront_code,
    parse_handler,
)

COGNITO_TRIGGER_HANDLER = "storefront/handlers/common/cognito_trigger.lambda_handler"


class CognitoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
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

        post_confirmation = _lambda.Function(
            self, "CognitoPostConfirmation",
            code=build_storefront_code(),
            handler=parse_handler(COGNITO_TRIGGER_HANDLER),
            runtime=LAMBDA_RUNTIME,
            layers=[build_dependencies_layer(self)],
            timeout=Duration.seconds(10),
        )
        self.user_pool.add_trigger(cognito.UserPoolOperation.POST_CONFIRMATION, post_confirmation)
