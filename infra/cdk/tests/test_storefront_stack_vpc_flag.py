"""Unit test for the functions.yml `vpc` flag on StorefrontStack._build_function — exercises
just that method against inline Lambda code, so (unlike the rest of this test package) it
needs no Docker bundling step.
"""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from aws_cdk.assertions import Match, Template

from functions_config import FunctionConfig, RouteConfig
from storefront_stack.storefront_stack import StorefrontStack

_INLINE_CODE = _lambda.Code.from_inline("def handler(event, context):\n    return {}\n")
_ROUTES = (RouteConfig(method="POST", path="/test", auth="cognito"),)


def _build(fn_config: FunctionConfig) -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    vpc = ec2.Vpc(stack, "Vpc", max_azs=1, nat_gateways=0)
    security_group = ec2.SecurityGroup(stack, "Sg", vpc=vpc)
    db_secret = secretsmanager.Secret(stack, "Secret")
    # An imported layer reference — no Docker bundling needed, unlike the real dependencies
    # layer from lambda_assets.build_dependencies_layer.
    layer = _lambda.LayerVersion.from_layer_version_arn(
        stack, "Layer", "arn:aws:lambda:ap-south-1:123456789012:layer:fake:1",
    )
    notifications_queue = sqs.Queue(stack, "Queue")

    # `_build_function` only uses `self` as the construct scope, so calling it unbound with
    # `stack` in that slot avoids constructing a full StorefrontStack (which needs Docker to
    # bundle its real Lambda code asset).
    StorefrontStack._build_function(
        stack, fn_config, code=_INLINE_CODE, layer=layer, vpc=vpc,
        security_group=security_group, db_secret=db_secret,
        db_host="db-host", db_name="db-name", notifications_queue=notifications_queue,
    )
    return Template.from_stack(stack)


def test_vpc_true_by_default_attaches_vpc_config():
    fn_config = FunctionConfig(name="test", handler="storefront/handlers/x_handler.handler", routes=_ROUTES)
    template = _build(fn_config)
    template.has_resource_properties("AWS::Lambda::Function", {"VpcConfig": Match.any_value()})


def test_vpc_false_omits_vpc_config():
    fn_config = FunctionConfig(
        name="test", handler="storefront/handlers/x_handler.handler", routes=_ROUTES, vpc=False,
    )
    template = _build(fn_config)
    template.has_resource_properties("AWS::Lambda::Function", {"VpcConfig": Match.absent()})
