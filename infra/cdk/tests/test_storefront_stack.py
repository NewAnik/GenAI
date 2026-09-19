"""CDK assertions for StorefrontStack — synthesizes alongside NetworkStack and CognitoStack
(no real AWS account needed; see conftest.py) and checks the expected Lambdas/API routes exist.

Requires Docker: the shared dependencies Lambda Layer bundles storefront/requirements.txt
(including psycopg2-binary's native extension) inside a Lambda-runtime container at synth
time — the function code asset itself is plain source and needs no Docker step.
"""
from __future__ import annotations

from aws_cdk.assertions import Match, Template

from .conftest import synth_stacks


def _synth() -> Template:
    _, _, storefront_stack = synth_stacks()
    return Template.from_stack(storefront_stack)


def test_creates_one_lambda_per_resource():
    template = _synth()
    # auth/cart/orders/payments — the Cognito trigger now lives in CognitoStack.
    functions = template.find_resources("AWS::Lambda::Function")
    assert len(functions) == 4


def test_creates_http_api_with_expected_route_count():
    template = _synth()
    template.resource_count_is("AWS::ApiGatewayV2::Api", 1)
    # 5 (auth) + ... — one route per entry across all 4 functions in functions.yml.
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    assert len(routes) == 15


def test_webhook_route_has_no_authorizer():
    template = _synth()
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Route",
        {"RouteKey": "POST /webhooks/payments", "AuthorizationType": "NONE"},
    )


def test_protected_route_uses_cognito_authorizer():
    template = _synth()
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Route",
        {"RouteKey": "POST /orders", "AuthorizerId": Match.any_value()},
    )


def test_every_function_is_attached_to_the_vpc_by_default():
    template = _synth()
    # functions.yml doesn't set `vpc: false` on anything today, so all 4 get VpcConfig.
    functions = template.find_resources(
        "AWS::Lambda::Function", {"Properties": {"VpcConfig": Match.any_value()}},
    )
    assert len(functions) == 4


def test_every_function_shares_the_one_dependencies_layer():
    template = _synth()
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    functions = template.find_resources(
        "AWS::Lambda::Function", {"Properties": {"Layers": Match.any_value()}},
    )
    assert len(functions) == 4
