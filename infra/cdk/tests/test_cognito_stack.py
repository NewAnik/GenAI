"""CDK assertions for CognitoStack (user pool, client, admin group, post-confirmation trigger).

Requires Docker: the dependencies Lambda Layer bundles storefront/requirements.txt (including
psycopg2-binary's native extension) inside a Lambda-runtime container at synth time — the
function code asset itself is plain source and needs no Docker step.
"""
from __future__ import annotations

from aws_cdk.assertions import Match, Template

from .conftest import synth_stacks


def _synth() -> Template:
    _, cognito_stack, _ = synth_stacks()
    return Template.from_stack(cognito_stack)


def test_creates_a_cognito_user_pool_retained_on_teardown():
    template = _synth()
    template.has_resource("AWS::Cognito::UserPool", {"DeletionPolicy": "Retain"})


def test_creates_admin_cognito_group():
    template = _synth()
    template.has_resource_properties("AWS::Cognito::UserPoolGroup", {"GroupName": "admin"})


def test_creates_post_confirmation_trigger_lambda():
    template = _synth()
    functions = template.find_resources("AWS::Lambda::Function")
    assert len(functions) == 1


def test_post_confirmation_trigger_uses_the_dependencies_layer():
    template = _synth()
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)
    template.has_resource_properties("AWS::Lambda::Function", {"Layers": Match.any_value()})
