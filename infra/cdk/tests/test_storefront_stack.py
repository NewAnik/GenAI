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
    # auth/cart/orders/payments/catalog/addresses — the Cognito trigger now lives in CognitoStack.
    functions = template.find_resources("AWS::Lambda::Function")
    assert len(functions) == 6


def test_creates_rest_api_with_expected_method_count():
    template = _synth()
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    # One method per route entry across every function in functions.yml. Filtered to AWS_PROXY
    # integrations to exclude the MOCK-integration CORS preflight OPTIONS methods
    # default_cors_preflight_options adds to every resource (see test_every_resource_below).
    methods = template.find_resources(
        "AWS::ApiGateway::Method", {"Properties": {"Integration": {"Type": "AWS_PROXY"}}},
    )
    assert len(methods) == 19


def test_webhook_route_has_no_authorizer():
    template = _synth()
    # /webhooks/payments and /catalog/gift-boxes are the only `auth: none` routes in
    # functions.yml — filtered to AWS_PROXY so the (also AuthorizationType NONE) CORS preflight
    # OPTIONS methods don't inflate this count.
    methods = template.find_resources(
        "AWS::ApiGateway::Method",
        {"Properties": {"AuthorizationType": "NONE", "Integration": {"Type": "AWS_PROXY"}}},
    )
    assert len(methods) == 2


def test_every_other_route_uses_cognito_authorizer():
    template = _synth()
    methods = template.find_resources(
        "AWS::ApiGateway::Method",
        {"Properties": {"AuthorizationType": "COGNITO_USER_POOLS", "AuthorizerId": Match.any_value()}},
    )
    assert len(methods) == 17


def test_every_function_is_attached_to_the_vpc_by_default():
    template = _synth()
    # functions.yml doesn't set `vpc: false` on anything today, so all 6 get VpcConfig.
    functions = template.find_resources(
        "AWS::Lambda::Function", {"Properties": {"VpcConfig": Match.any_value()}},
    )
    assert len(functions) == 6


def test_every_function_shares_the_one_dependencies_layer():
    template = _synth()
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    functions = template.find_resources(
        "AWS::Lambda::Function", {"Properties": {"Layers": Match.any_value()}},
    )
    assert len(functions) == 6


def test_every_resource_gets_a_cors_preflight_options_method():
    template = _synth()
    # One per unique resource path segment functions.yml's 19 routes expand into (intermediate
    # segments like /orders and /orders/{order_id} count too, not just the leaf routes), plus the
    # API's own root resource ("/") — see storefront_stack.py's module docstring for why CORS is
    # needed at all here.
    options_methods = template.find_resources(
        "AWS::ApiGateway::Method", {"Properties": {"HttpMethod": "OPTIONS"}},
    )
    assert len(options_methods) == 24


def test_cors_defaults_to_the_local_dev_origin_when_apiCorsOrigins_is_unset():
    template = _synth()
    template.has_resource_properties(
        "AWS::ApiGateway::Method",
        {
            "HttpMethod": "OPTIONS",
            "Integration": {
                "IntegrationResponses": Match.array_with([
                    Match.object_like({
                        "ResponseParameters": Match.object_like({
                            "method.response.header.Access-Control-Allow-Origin":
                                "'http://localhost:3000'",
                        }),
                    }),
                ]),
            },
        },
    )


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
