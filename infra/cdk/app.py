from __future__ import annotations

import aws_cdk as cdk
from cognito_stack.cognito_stack import CognitoStack
from network_stack.network_stack import NetworkStack
from storefront_stack.storefront_stack import StorefrontStack

app = cdk.App()
network_stack = NetworkStack(app, "NetworkStack")
cognito_stack = CognitoStack(app, "CognitoStack")
StorefrontStack(
    app, "StorefrontStack",
    vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
    user_pool=cognito_stack.user_pool, user_pool_client=cognito_stack.user_pool_client,
)
app.synth()
