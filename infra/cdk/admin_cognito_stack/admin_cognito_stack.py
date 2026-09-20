"""CDK stack for the admin portal's identity: a Cognito User Pool for internal staff, separate
from CognitoStack's storefront customer pool (see the migration plan referenced in this repo's
CLAUDE.md for the full rationale). Split out into its own stack for the same reason CognitoStack
is split from StorefrontStack — identity infra must outlive routine API redeploys, and
`RemovalPolicy.RETAIN` on the pool means a stack teardown never deletes real staff accounts.

Unlike the storefront pool, `self_sign_up_enabled=False`: staff accounts are never self-service.
An admin provisions each account by hand (via `AdminCreateUser` — see
wrapped-and-more-admin/scripts/provision-staff.mjs) and assigns it to exactly one of the four
groups below, mirroring wrapped-and-more-admin's `STAFF_ROLES`
(`super_admin`, `admin`, `ops`, `sales`) — an account in none of these groups (the old `org_member`
role) authenticates against Cognito but is rejected by every admin API route, since
`admin_api/services/auth_service.py`'s `require_group` never matches an empty intersection.

No post-confirmation trigger: unlike the storefront pool's self-service `SignUp`→`ConfirmSignUp`
flow, `AdminCreateUser` does not fire `PostConfirmation` at all, so relying on one here would
silently never run. The local `users` profile row is instead provisioned synchronously, in the
same script/call that creates the Cognito account (see provision-staff.mjs) — a deliberate
design choice, not an oversight.
"""
from __future__ import annotations

from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from constructs import Construct

STAFF_GROUPS = ("super_admin", "admin", "ops", "sales")


class AdminCognitoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.user_pool = cognito.UserPool(
            self, "AdminUserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_uppercase=False,
                require_digits=True, require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            # A stack teardown/redeploy must never delete real staff accounts.
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.user_pool_client = self.user_pool.add_client(
            "AdminAppClient",
            generate_secret=False,  # public/SPA client — the admin app calls Cognito directly
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
        )
        self.groups = {
            group: cognito.CfnUserPoolGroup(
                self, f"{group.title().replace('_', '')}Group",
                user_pool_id=self.user_pool.user_pool_id, group_name=group,
            )
            for group in STAFF_GROUPS
        }

        # Consumed by wrapped-and-more-admin/scripts/provision-staff.mjs (--user-pool-id) and
        # the admin app's own .env (VITE_COGNITO_CLIENT_ID) — without these, both would have to
        # be found by hand via `aws cognito-idp list-user-pools`.
        CfnOutput(self, "AdminUserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "AdminAppClientId", value=self.user_pool_client.user_pool_client_id)
