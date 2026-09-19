"""CDK assertions for StorefrontStack — synthesizes alongside NetworkStack and CognitoStack
(no real AWS account needed; see conftest.py) and checks the expected Lambdas/API methods exist.

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


def test_creates_rest_api_with_expected_method_count():
    template = _synth()
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    # 6 (auth) + ... — one method per entry across all 4 functions in functions.yml.
    methods = template.find_resources("AWS::ApiGateway::Method")
    assert len(methods) == 16


def test_webhook_route_has_no_authorizer():
    template = _synth()
    # Only /webhooks/payments sets `auth: none` in functions.yml.
    methods = template.find_resources(
        "AWS::ApiGateway::Method", {"Properties": {"AuthorizationType": "NONE"}},
    )
    assert len(methods) == 1


def test_every_other_route_uses_cognito_authorizer():
    template = _synth()
    methods = template.find_resources(
        "AWS::ApiGateway::Method",
        {"Properties": {"AuthorizationType": "COGNITO_USER_POOLS", "AuthorizerId": Match.any_value()}},
    )
    assert len(methods) == 15


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


def test_no_custom_domain_by_default():
    template = _synth()
    template.resource_count_is("AWS::ApiGateway::DomainName", 0)


def test_custom_domain_uses_tls_1_2_when_configured():
    _, _, storefront_stack = synth_stacks({
        "apiDomainName": "api.wrappedandmore.in",
        "apiCertificateArn": "arn:aws:acm:ap-south-1:123456789012:certificate/abc-123",
    })
    template = Template.from_stack(storefront_stack)
    template.has_resource_properties(
        "AWS::ApiGateway::DomainName",
        {"DomainName": "api.wrappedandmore.in", "SecurityPolicy": "TLS_1_2"},
    )
