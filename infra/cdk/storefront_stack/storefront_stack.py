"""CDK stack for the storefront API: reads infra/config/functions.yml and loops over it to
build one Lambda per resource plus a shared HTTP API, authenticated against the Cognito User
Pool built by CognitoStack (see that stack's docstring for why identity lives separately).
Adding an endpoint means adding an entry to functions.yml, not new CDK code here — see that
file's header comment. See the migration plan (and this repo's CLAUDE.md) for the full
rationale behind the architecture.

Requires Docker at synth/deploy time: dependencies are bundled into a shared Lambda Layer
inside a Lambda-runtime container (see lambda_assets.build_dependencies_layer), which
`psycopg2-binary`'s native extension needs regardless of the host machine's OS. The function
code asset itself is plain source and needs no Docker step.

Takes the VPC and Postgres (RDS) security group from NetworkStack (see that stack's docstring
for why the VPC is CDK-managed but the RDS instance itself deliberately isn't) — this stack
only adds its own Lambda-facing security group and an ingress rule into the RDS one.

Expects this CDK context value (pass via `-c key=value`, or cdk.context.json):
  dbSecretArn - Secrets Manager secret ARN holding {host, port, dbname, username, password}
               (the standard shape for an RDS-managed credentials secret) for the RDS
               instance created by hand in the console — not guessed at or defaulted here,
               since that instance doesn't exist until someone creates it (see NetworkStack).
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_authorizers as apigwv2_authorizers
from aws_cdk import aws_apigatewayv2_integrations as apigwv2_integrations
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct
from functions_config import FunctionConfig, load_functions
from lambda_assets import (
    LAMBDA_RUNTIME,
    build_dependencies_layer,
    build_storefront_code,
    parse_handler,
)

_INFRA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = _INFRA_ROOT / "config" / "functions.yml"


class StorefrontStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc,
                 db_security_group: ec2.ISecurityGroup, user_pool: cognito.IUserPool,
                 user_pool_client: cognito.IUserPoolClient, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        functions = load_functions(CONFIG_PATH)

        db_secret_arn = self.node.try_get_context("dbSecretArn")
        if not db_secret_arn:
            raise ValueError(
                "StorefrontStack requires -c dbSecretArn=... (see this file's module docstring)"
            )

        db_secret = secretsmanager.Secret.from_secret_complete_arn(self, "DbSecret", db_secret_arn)

        lambda_security_group = ec2.SecurityGroup(
            # CloudFormation's GroupDescription disallows angle brackets - no "->" here.
            self, "StorefrontLambdaSg", vpc=vpc, description="Storefront Lambdas to Postgres",
            allow_all_outbound=True,
        )
        # Not `db_security_group.add_ingress_rule(lambda_security_group, ...)`: that adds the
        # rule to db_security_group's own stack (NetworkStack) referencing lambda_security_group
        # from this stack, which makes NetworkStack depend on StorefrontStack — a cycle, since
        # StorefrontStack already depends on NetworkStack for `vpc`/`db_security_group`. Scoping
        # the rule as its own resource here instead keeps the dependency one-directional.
        ec2.CfnSecurityGroupIngress(
            self, "RdsIngressFromLambdas",
            ip_protocol="tcp", from_port=5432, to_port=5432,
            group_id=db_security_group.security_group_id,
            source_security_group_id=lambda_security_group.security_group_id,
            description="Storefront Lambdas to Postgres",
        )

        storefront_code = build_storefront_code()
        dependencies_layer = build_dependencies_layer(self)

        authorizer = apigwv2_authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer", user_pool, user_pool_clients=[user_pool_client],
        )

        http_api = apigwv2.HttpApi(self, "StorefrontApi", api_name="storefront-api")

        for fn_config in functions:
            fn = self._build_function(
                fn_config, code=storefront_code, layer=dependencies_layer, vpc=vpc,
                security_group=lambda_security_group, db_secret=db_secret,
            )
            integration = apigwv2_integrations.HttpLambdaIntegration(
                f"{fn_config.name.capitalize()}Integration", fn
            )
            for route in fn_config.routes:
                http_api.add_routes(
                    path=route.path,
                    methods=[apigwv2.HttpMethod(route.method)],
                    integration=integration,
                    authorizer=(authorizer if route.requires_cognito else None),
                )

        self.http_api = http_api

    def _build_function(self, fn_config: FunctionConfig, *, code: _lambda.Code,
                         layer: _lambda.ILayerVersion, vpc: ec2.IVpc,
                         security_group: ec2.ISecurityGroup,
                         db_secret: secretsmanager.ISecret) -> _lambda.Function:
        environment = {
            "DB_SECRET_ARN": db_secret.secret_arn,
            "GST_RATE": fn_config.gst_rate,
        }
        if fn_config.default_warehouse_id is not None:
            environment["DEFAULT_WAREHOUSE_ID"] = str(fn_config.default_warehouse_id)
        if fn_config.payment_webhook_secret_arn is not None:
            environment["PAYMENT_WEBHOOK_SECRET_ARN"] = fn_config.payment_webhook_secret_arn

        # `vpc: false` in functions.yml opts a function out of the VPC entirely. Only safe for
        # functions that don't need DB_SECRET_ARN's Postgres access — there's no NAT gateway on
        # this VPC, so a function placed in it gets no outbound internet access either (only
        # what's reachable inside the VPC/via VPC endpoints). Defaults to true (current/only
        # behavior before this flag existed) since every function today talks to Postgres.
        network_kwargs = (
            {"vpc": vpc, "security_groups": [security_group]} if fn_config.vpc else {}
        )

        fn = _lambda.Function(
            self, f"{fn_config.name.capitalize()}Function",
            code=code,
            handler=parse_handler(fn_config.handler),
            runtime=LAMBDA_RUNTIME,
            layers=[layer],
            memory_size=fn_config.memory,
            timeout=Duration.seconds(fn_config.timeout),
            # A conservative ceiling on concurrent DB connections this function can open —
            # each concurrent execution environment holds one live Postgres connection (see
            # storefront/db/database.py). Tune once real traffic is known; RDS Proxy is the
            # correct long-term fix if this needs to grow much further.
            reserved_concurrent_executions=fn_config.reserved_concurrency,
            environment=environment,
            **network_kwargs,
        )
        db_secret.grant_read(fn)
        return fn
