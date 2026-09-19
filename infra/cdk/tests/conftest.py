"""Shared fake CDK context + app-building helper for stack tests — NetworkStack, CognitoStack
and StorefrontStack all need to synthesize together since StorefrontStack cross-references the
other two stacks' VPC/security group/user pool.
"""
from __future__ import annotations

import aws_cdk as cdk

from cognito_stack.cognito_stack import CognitoStack
from network_stack.network_stack import NetworkStack
from storefront_stack.storefront_stack import StorefrontStack

FAKE_CONTEXT = {
    "dbSecretArn": "arn:aws:secretsmanager:ap-south-1:123456789012:secret:storefront-db-abc123",
    "dbHost": "storefront-db.abc123.ap-south-1.rds.amazonaws.com",
    "dbName": "storefront",
}


def synth_stacks(
    extra_context: dict | None = None,
) -> tuple[NetworkStack, CognitoStack, StorefrontStack]:
    app = cdk.App(context={**FAKE_CONTEXT, **(extra_context or {})})
    network_stack = NetworkStack(app, "TestNetworkStack")
    cognito_stack = CognitoStack(
        app, "TestCognitoStack",
        vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
    )
    storefront_stack = StorefrontStack(
        app, "TestStorefrontStack",
        vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
        user_pool=cognito_stack.user_pool,
    )
    return network_stack, cognito_stack, storefront_stack
