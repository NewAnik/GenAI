"""CDK stack for the admin API: reads infra/config/admin_functions.yml and loops over it to build
one Lambda per resource plus a shared REST API (API Gateway v1), authenticated against the Admin
Cognito User Pool built by AdminCognitoStack. Structurally a near-copy of storefront_stack.py —
see that file's docstring for the reasoning behind REST API v1 vs. HTTP API v2, the Docker-bundled
dependency layer, and the VPC/RDS security-group wiring; this docstring only calls out where the
admin API differs.

Differences from StorefrontStack:
- Bound to AdminCognitoStack's pool, not CognitoStack's — a Cognito token issued by the storefront
  customer pool never authenticates here, and vice versa.
- CORS defaults to the admin app's own known origins (`http://localhost:5173` for Vite dev), never
  a public/open origin list — this is an internal tool, not a storefront called from a public site.
- No `gst_rate`/`default_warehouse_id`/`payment_webhook_secret_arn` per-function environment
  wiring (admin_functions_config.py's AdminFunctionConfig has no such fields).
- A new S3 bucket for catalogue images (replacing Supabase Storage), private, read via CloudFront
  (see this stack's `_build_image_bucket`/`_build_image_cdn`) — kept in this stack rather than a
  separate one, since catalogue images are recreatable/re-uploadable business assets, unlike a
  Cognito user pool's real identities, so they don't need `RemovalPolicy.RETAIN`-level teardown
  protection.

Expects the same CDK context values as StorefrontStack (`dbSecretArn`, `dbHost`, `dbName` —
required; `apiDomainName`/`apiCertificateArn` — optional custom domain), plus:
  adminApiCorsOrigins - comma-separated allowed origins for the admin app (defaults to
                        http://localhost:5173 when unset).

Also takes `notifications_queue` (NotificationsStack's SQS queue), same reasoning as
StorefrontStack: the `orders` function (its bespoke status-change endpoint) enqueues a
notification rather than emailing directly, since this stack's Lambdas have no internet egress.
"""
from __future__ import annotations

from pathlib import Path

from admin_functions_config import AdminFunctionConfig, load_admin_functions
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct
from lambda_assets import (
    LAMBDA_RUNTIME,
    build_admin_code,
    build_admin_dependencies_layer,
    parse_handler,
)

_INFRA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = _INFRA_ROOT / "config" / "admin_functions.yml"


class AdminApiStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, vpc: ec2.IVpc,
                 db_security_group: ec2.ISecurityGroup, user_pool: cognito.IUserPool,
                 notifications_queue: sqs.IQueue, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        functions = load_admin_functions(CONFIG_PATH)

        db_secret_arn = self.node.try_get_context("dbSecretArn")
        db_host = self.node.try_get_context("dbHost")
        db_name = self.node.try_get_context("dbName")
        if not (db_secret_arn and db_host and db_name):
            raise ValueError(
                "AdminApiStack requires -c dbSecretArn=... -c dbHost=... -c dbName=... "
                "(see this file's module docstring)"
            )

        db_secret = secretsmanager.Secret.from_secret_complete_arn(self, "DbSecret", db_secret_arn)

        # NetworkStack's VPC has no NAT gateway, so a VPC-placed Lambda (every function here,
        # per admin_functions.yml) has no route to S3 for the `images` function's delete_object
        # call without this — a Gateway endpoint (unlike an interface endpoint) is free and
        # attaches directly to the VPC's route tables, so it's safe to add from this consuming
        # stack rather than needing a NetworkStack change.
        vpc.add_gateway_endpoint("AdminApiS3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)

        lambda_security_group = ec2.SecurityGroup(
            self, "AdminApiLambdaSg", vpc=vpc, description="Admin API Lambdas to Postgres",
            allow_all_outbound=True,
        )
        # One-directional dependency, same reasoning as StorefrontStack's identical pattern: a
        # rule scoped on db_security_group.add_ingress_rule would make NetworkStack depend on
        # this stack (it already depends on NetworkStack for vpc/db_security_group) — a cycle.
        ec2.CfnSecurityGroupIngress(
            self, "RdsIngressFromAdminApiLambdas",
            ip_protocol="tcp", from_port=5432, to_port=5432,
            group_id=db_security_group.security_group_id,
            source_security_group_id=lambda_security_group.security_group_id,
            description="Admin API Lambdas to Postgres",
        )

        admin_code = build_admin_code()
        dependencies_layer = build_admin_dependencies_layer(self)

        # Built before the function loop below since _build_function grants the `images`
        # function read/write access to it.
        self.image_bucket = self._build_image_bucket()

        authorizer = apigateway.CognitoUserPoolsAuthorizer(
            self, "AdminCognitoAuthorizer", cognito_user_pools=[user_pool],
        )

        rest_api = apigateway.RestApi(
            self, "AdminApi", rest_api_name="admin-api",
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
                fn_config, code=admin_code, layer=dependencies_layer, vpc=vpc,
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
            CfnOutput(self, "AdminApiRegionalDomainName",
                      value=rest_api.domain_name.domain_name_alias_domain_name)

        self.rest_api = rest_api
        self.image_cdn = self._build_image_cdn(self.image_bucket)
        CfnOutput(self, "CatalogImagesCdnDomainName", value=self.image_cdn.domain_name)

    def _cors_allow_origins(self) -> list[str]:
        raw = self.node.try_get_context("adminApiCorsOrigins")
        if not raw:
            return ["http://localhost:5173"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    def _build_domain_name_options(self) -> apigateway.DomainNameOptions | None:
        domain_name = self.node.try_get_context("apiDomainName")
        certificate_arn = self.node.try_get_context("apiCertificateArn")
        if not (domain_name and certificate_arn):
            return None

        certificate = acm.Certificate.from_certificate_arn(self, "AdminApiCertificate", certificate_arn)
        return apigateway.DomainNameOptions(
            domain_name=domain_name, certificate=certificate,
            endpoint_type=apigateway.EndpointType.REGIONAL,
            security_policy=apigateway.SecurityPolicy.TLS_1_2,
        )

    def _build_function(self, fn_config: AdminFunctionConfig, *, code: _lambda.Code,
                         layer: _lambda.ILayerVersion, vpc: ec2.IVpc,
                         security_group: ec2.ISecurityGroup,
                         db_secret: secretsmanager.ISecret,
                         db_host: str, db_name: str,
                         notifications_queue: sqs.IQueue) -> _lambda.Function:
        environment = {
            "DB_SECRET_ARN": db_secret.secret_arn,
            "DB_HOST": db_host,
            "DB_NAME": db_name,
        }
        if fn_config.name == "orders":
            environment["ORDER_NOTIFICATIONS_QUEUE_URL"] = notifications_queue.queue_url
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
            reserved_concurrent_executions=fn_config.reserved_concurrency,
            environment=environment,
            **network_kwargs,
        )
        db_secret.grant_read(fn)
        if fn_config.name == "images":
            self._grant_image_bucket_access(fn)
        if fn_config.name == "orders":
            notifications_queue.grant_send_messages(fn)
        return fn

    def _build_image_bucket(self) -> s3.Bucket:
        # Private — no public read. Reads go through CloudFront (see _build_image_cdn); writes
        # go through admin_api/handlers/images_handler.py's presigned PUT URLs, never a public
        # ACL. Not RETAIN: catalogue images are recreatable business assets, re-uploadable from
        # source files, unlike a Cognito user pool's real identities.
        return s3.Bucket(
            self, "CatalogImagesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=self._cors_allow_origins(),
                    allowed_headers=["*"],
                )
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

    def _build_image_cdn(self, bucket: s3.Bucket) -> cloudfront.Distribution:
        return cloudfront.Distribution(
            self, "CatalogImagesCdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
        )

    def _grant_image_bucket_access(self, fn: _lambda.Function) -> None:
        self.image_bucket.grant_read_write(fn)
        fn.add_environment("CATALOG_IMAGES_BUCKET", self.image_bucket.bucket_name)
