"""CDK stack for the storefront's networking: the VPC, its subnets, and the security group
Postgres (RDS) sits behind. Deliberately stops short of the RDS instance itself — that's
created by hand in the console against this stack's VPC/security group (see the CfnOutputs
below), so a CDK diff can never force-replace or delete the live database the way an
instance-class/engine-version change on a CDK-managed `DatabaseInstance` could. StorefrontStack
and CognitoStack import `vpc` / `db_security_group` from here rather than doing their own
`Vpc.from_lookup` by hand-copied ID.

No NAT gateway is provisioned (cost — this is a low-traffic storefront, not a reason to pay
for one AZ-redundant NAT per AZ). That means Lambdas placed in the private subnets get no
outbound internet access, only what's reachable inside the VPC — see the `vpc` flag in
infra/config/functions.yml for how a function that needs both Postgres *and* the public
internet (a payment gateway callout, say) should be reconsidered, since it can't have both
without a NAT gateway.
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self, "StorefrontVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                # Kept even though nothing uses it yet, so adding a NAT gateway later (to lift
                # the no-internet-from-private-subnets constraint above) doesn't require
                # recreating subnets.
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(
                    name="Private", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24,
                ),
            ],
        )

        self.db_security_group = ec2.SecurityGroup(
            self, "RdsSecurityGroup", vpc=self.vpc,
            # CloudFormation's GroupDescription only allows a narrow ASCII set (no em-dash,
            # no angle brackets) - see CloudFormation-Validate::F3031.
            description="Storefront Postgres (RDS): each consumer (e.g. the Lambda security "
                        "group in StorefrontStack) adds its own ingress rule, none here by default.",
            allow_all_outbound=False,
        )

        private_subnet_ids = self.vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
        ).subnet_ids

        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(self, "PrivateSubnetIds", value=",".join(private_subnet_ids))
        CfnOutput(self, "RdsSecurityGroupId", value=self.db_security_group.security_group_id)
