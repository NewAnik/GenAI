"""Unit test for storefront.handlers.common.auth.get_claims — specifically that it reads the
flat `requestContext.authorizer.claims` shape API Gateway REST API's `CognitoUserPoolsAuthorizer`
produces, not HTTP API (v2) JWT authorizer's extra-nested `authorizer.jwt.claims`."""
from __future__ import annotations

from handlers.common.auth import get_claims


def test_reads_rest_api_cognito_authorizer_claims():
    event = {"requestContext": {"authorizer": {"claims": {"sub": "abc-123"}}}}
    assert get_claims(event) == {"sub": "abc-123"}


def test_missing_authorizer_returns_empty_dict():
    assert get_claims({"requestContext": {}}) == {}
    assert get_claims({}) == {}


def test_does_not_look_for_the_old_http_api_v2_jwt_nesting():
    # HTTP API (v2)'s JWT authorizer shape — should NOT be picked up post-migration.
    event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "abc-123"}}}}}
    assert get_claims(event) == {}
