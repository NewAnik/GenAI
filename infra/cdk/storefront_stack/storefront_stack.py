"""CDK stack for the storefront API: reads infra/config/functions.yml and loops over it to
build one Lambda per resource plus a shared REST API (API Gateway v1 — not HTTP API/v2),
authenticated against the Cognito User Pool built by CognitoStack (see that stack's docstring
for why identity lives separately). Adding an endpoint means adding an entry to functions.yml,
not new CDK code here — see that file's header comment. See the migration plan (and this
repo's CLAUDE.md) for the full rationale behind the architecture.

REST API's `CognitoUserPoolsAuthorizer` (unlike HTTP API's `HttpUserPoolAuthorizer`) only takes
the User Pool, not a specific app client — any confirmed user from the pool authenticates
regardless of which client issued the token, since REST API's Cognito authorizer has no
per-client restriction. That's why this stack no longer needs `user_pool_client` from
CognitoStack (which still creates/exposes it, for the site's own direct-to-Cognito sign-in).

Requires Docker at synth/deploy time: dependencies are bundled into a shared Lambda Layer
inside a Lambda-runtime container (see lambda_assets.build_dependencies_layer), which
`psycopg2-binary`'s native extension needs regardless of the host machine's OS. The function
code asset itself is plain source and needs no Docker step.

Takes the VPC and Postgres (RDS) security group from NetworkStack (see that stack's docstring
for why the VPC is CDK-managed but the RDS instance itself deliberately isn't) — this stack
only adds its own Lambda-facing security group and an ingress rule into the RDS one.

Expects these CDK context values (pass via `-c key=value`, or cdk.context.json):
  dbSecretArn - ARN of the RDS-managed master-user secret ({username, password}) for the RDS
               instance created by hand in the console — not guessed at or defaulted here,
               since that instance doesn't exist until someone creates it (see NetworkStack).
               That secret holds only login credentials, not host/port/dbname (RDS doesn't
               put connection endpoints there — an instance can host multiple databases), so:
  dbHost      - the RDS instance's endpoint address.
  dbName      - the database name to connect to.
               Both passed as plain (non-secret) Lambda env vars — see storefront/config.py.

Optionally, `catalogImagesCdnDomain` (the admin app's CatalogImagesCdn CloudFront domain — see
GenAI/infra/cdk/admin_api_stack/admin_api_stack.py's CfnOutput of the same name) is passed as
`CATALOG_IMAGES_CDN_DOMAIN` to the `catalog` function only (see `_build_function`), so it can
resolve gift_box_images' relative object keys into full URLs. A non-secret, effectively-static
domain name — a plain context value rather than a CDK cross-stack reference, same tradeoff
`dbHost`/`dbName` already accept, and it avoids adding a first-ever dependency edge between this
stack and AdminApiStack.

Takes `notifications_queue` (NotificationsStack's SQS queue) so the `orders` function can enqueue
a status-change notification for the separate, non-VPC email Lambda to send — see
notifications_stack.py's docstring for why that Lambda can't live here and call Resend directly.

Optionally, `apiDomainName` + `apiCertificateArn` context values attach a custom domain to the
REST API with `SecurityPolicy: TLS_1_2` (the AWS-recommended minimum — the default
`*.execute-api.<region>.amazonaws.com` endpoint already enforces TLS 1.2 on AWS's side with no
config needed, so this only matters once a custom domain is in play). Requires an ACM
certificate already issued in this stack's region (regional API) for that domain — not created
here, since that's an out-of-band DNS-validation step. Point your own DNS (a Route 53 alias,
say) at the CfnOutput'd regional domain name once deployed.

This API is meant to be called cross-origin from the public site (wrapped-and-more, a static
export served from its own domain — see this repo's CLAUDE.md), so every resource gets a CORS
preflight (OPTIONS) via `default_cors_preflight_options` on the REST API root, inherited by
every path `resource_for_path` creates. Allowed origins come from the optional `apiCorsOrigins`
context value (comma-separated), defaulting to `http://localhost:3000` (the site's local dev
origin) when unset — set it explicitly for any deployed environment, e.g.
`-c apiCorsOrigins=https://wrappedandmore.in,https://www.wrappedandmore.in`. Only POST is
allowed (every route in functions.yml is POST-only by design) and `Authorization` is one of
Cors.DEFAULT_HEADERS already, since the site sends the Cognito token that way, not as a
cookie — so `allow_credentials` stays off.
"""
from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
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
                 notifications_queue: sqs.IQueue, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        functions = load_functions(CONFIG_PATH)

        db_secret_arn = self.node.try_get_context("dbSecretArn")
        db_host = self.node.try_get_context("dbHost")
        db_name = self.node.try_get_context("dbName")
        if not (db_secret_arn and db_host and db_name):
            raise ValueError(
                "StorefrontStack requires -c dbSecretArn=... -c dbHost=... -c dbName=... "
                "(see this file's module docstring)"
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

        authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer", cognito_user_pools=[user_pool],
        )

        rest_api = apigateway.RestApi(
            self, "StorefrontApi", rest_api_name="storefront-api",
            endpoint_types=[apigateway.EndpointType.REGIONAL],
            domain_name=self._build_domain_name_options(),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=self._cors_allow_origins(),
                allow_methods=["POST"],
                allow_headers=apigateway.Cors.DEFAULT_HEADERS,
            ),
        )

        for fn_config in functions:
            fn = self._build_function(
                fn_config, code=storefront_code, layer=dependencies_layer, vpc=vpc,
                security_group=lambda_security_group, db_secret=db_secret,
                db_host=db_host, db_name=db_name, notifications_queue=notifications_queue,
            )
            integration = apigateway.LambdaIntegration(fn)
            for route in fn_config.routes:
                resource = rest_api.root.resource_for_path(route.path)
                resource.add_method(
                    route.method, integration,
                    authorizer=authorizer if route.requires_cognito else None,
                )

        if rest_api.domain_name is not None:
            CfnOutput(self, "ApiRegionalDomainName",
                      value=rest_api.domain_name.domain_name_alias_domain_name)

        self.rest_api = rest_api

    def _cors_allow_origins(self) -> list[str]:
        raw = self.node.try_get_context("apiCorsOrigins")
        if not raw:
            return ["http://localhost:3000"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def _build_domain_name_options(self) -> apigateway.DomainNameOptions | None:
        domain_name = self.node.try_get_context("apiDomainName")
        certificate_arn = self.node.try_get_context("apiCertificateArn")
        if not (domain_name and certificate_arn):
            return None

        certificate = acm.Certificate.from_certificate_arn(self, "ApiCertificate", certificate_arn)
        # TLS_1_2 is the AWS-recommended minimum for API Gateway custom domains — the default
        # execute-api endpoint already enforces this with no config, but a custom domain name
        # defaults to a broader/legacy policy unless told otherwise.
        return apigateway.DomainNameOptions(
            domain_name=domain_name, certificate=certificate,
            endpoint_type=apigateway.EndpointType.REGIONAL,
            security_policy=apigateway.SecurityPolicy.TLS_1_2,
        )

    def _build_function(self, fn_config: FunctionConfig, *, code: _lambda.Code,
                         layer: _lambda.ILayerVersion, vpc: ec2.IVpc,
                         security_group: ec2.ISecurityGroup,
                         db_secret: secretsmanager.ISecret,
                         db_host: str, db_name: str,
                         notifications_queue: sqs.IQueue) -> _lambda.Function:
        environment = {
            "DB_SECRET_ARN": db_secret.secret_arn,
            # Not part of db_secret: that's RDS's own master-user secret (username/password
            # only) — host/dbname aren't sensitive and the RDS instance isn't CDK-managed (see
            # NetworkStack's docstring), so there's no CDK-known endpoint to read them from.
            "DB_HOST": db_host,
            "DB_NAME": db_name,
            "GST_RATE": fn_config.gst_rate,
        }
        if fn_config.default_warehouse_id is not None:
            environment["DEFAULT_WAREHOUSE_ID"] = str(fn_config.default_warehouse_id)
        if fn_config.payment_webhook_secret_arn is not None:
            environment["PAYMENT_WEBHOOK_SECRET_ARN"] = fn_config.payment_webhook_secret_arn
        if fn_config.name == "catalog":
            cdn_domain = self.node.try_get_context("catalogImagesCdnDomain")
            if cdn_domain:
                environment["CATALOG_IMAGES_CDN_DOMAIN"] = cdn_domain
        if fn_config.name == "orders":
            environment["ORDER_NOTIFICATIONS_QUEUE_URL"] = notifications_queue.queue_url

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
        if fn_config.name == "orders":
            notifications_queue.grant_send_messages(fn)
        return fn
