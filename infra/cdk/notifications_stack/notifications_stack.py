"""CDK stack for order-status-change email notifications.

The Lambdas that actually place/update orders (StorefrontStack's `orders` function,
AdminApiStack's `orders` function) sit in the shared VPC to reach Postgres, and that VPC has no
NAT gateway (see network_stack.py) — no route to the public internet, so they can't call a
third-party REST API like Resend directly. This stack decouples the two: those Lambdas enqueue a
small JSON message to `queue` (reachable from inside the VPC via NetworkStack's `SqsEndpoint`,
no NAT needed), and the Lambda built here — deliberately placed *outside* the VPC, since it needs
internet egress and never touches Postgres — consumes the queue and calls Resend.

Expects one CDK context value:
  resendApiKeySecretArn - ARN of a Secrets Manager secret holding the Resend API key as a plain
                          string. A human must create this secret (and verify the sending domain
                          in Resend) before this stack can be deployed for real — this plan/stack
                          can't mint a real API key.
"""
from __future__ import annotations

from aws_cdk import Duration, Stack
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from constructs import Construct
from lambda_assets import LAMBDA_RUNTIME, build_notifications_code, parse_handler


class NotificationsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.dead_letter_queue = sqs.Queue(
            self, "OrderNotificationsDlq", retention_period=Duration.days(14),
        )
        self.queue = sqs.Queue(
            self, "OrderNotificationsQueue",
            visibility_timeout=Duration.seconds(30),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3, queue=self.dead_letter_queue,
            ),
        )

        resend_secret_arn = self.node.try_get_context("resendApiKeySecretArn")
        if not resend_secret_arn:
            raise ValueError(
                "NotificationsStack requires -c resendApiKeySecretArn=... "
                "(see this file's module docstring)"
            )
        resend_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "ResendSecret", resend_secret_arn,
        )

        # Deliberately not placed in the VPC (no `vpc=`/`security_groups=` kwargs) — this
        # function needs default internet egress to reach Resend and never touches Postgres, the
        # mirror image of every other function in this repo (see functions.yml's `vpc:` flag).
        self.email_fn = _lambda.Function(
            self, "OrderEmailFunction",
            code=build_notifications_code(),
            handler=parse_handler("notifications/handler.lambda_handler"),
            runtime=LAMBDA_RUNTIME,
            timeout=Duration.seconds(15),
            memory_size=256,
            environment={"RESEND_API_KEY_SECRET_ARN": resend_secret.secret_arn},
        )
        resend_secret.grant_read(self.email_fn)
        self.email_fn.add_event_source(
            lambda_event_sources.SqsEventSource(
                self.queue, batch_size=10, report_batch_item_failures=True,
            )
        )
