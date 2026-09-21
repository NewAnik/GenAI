from __future__ import annotations

import aws_cdk as cdk
from admin_api_stack.admin_api_stack import AdminApiStack
from admin_cognito_stack.admin_cognito_stack import AdminCognitoStack
from cognito_stack.cognito_stack import CognitoStack
from network_stack.network_stack import NetworkStack
from notifications_stack.notifications_stack import NotificationsStack
from storefront_stack.storefront_stack import StorefrontStack

app = cdk.App()
network_stack = NetworkStack(app, "NetworkStack")
notifications_stack = NotificationsStack(app, "NotificationsStack")
cognito_stack = CognitoStack(
    app, "CognitoStack",
    vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
)
StorefrontStack(
    app, "StorefrontStack",
    vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
    user_pool=cognito_stack.user_pool,
    notifications_queue=notifications_stack.queue,
)
admin_cognito_stack = AdminCognitoStack(app, "AdminCognitoStack")
AdminApiStack(
    app, "AdminApiStack",
    vpc=network_stack.vpc, db_security_group=network_stack.db_security_group,
    user_pool=admin_cognito_stack.user_pool,
    notifications_queue=notifications_stack.queue,
)
app.synth()
