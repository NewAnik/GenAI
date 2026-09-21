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

Every VPC-placed Lambda resolves its DB credentials via Secrets Manager (`DB_SECRET_ARN`,
see storefront/config.py) at cold start, before it ever touches Postgres — without a NAT
gateway that call has nowhere to go, and hangs until Lambda's hard ~10s init-phase timeout
kills the invocation (a real incident: the Cognito post-confirmation trigger did exactly
this once it was placed in the VPC). The Secrets Manager interface endpoint below is what
makes that call resolve entirely inside the VPC instead.

A small EC2 instance (`bastion`) is an SSM Session Manager target for developers who need
direct DB access (psql, migrations) from a laptop. It sits in the *public* subnet, which (per
CDK's default for SubnetType.PUBLIC) auto-assigns every instance there a public IP, and that's
what lets it reach SSM's own endpoints over the internet via the subnet's IGW route — no VPC
interface endpoints needed for SSM itself, unlike the Lambdas, which stay in the
private-isolated subnet with no such path. The public IP is not an open door: no security
group inbound rule exists for it (no SSH, nothing), so it's only ever reachable through SSM.
Reach it with the SSM port-forwarding document, then point a local client at the forwarded
port:

  aws ssm start-session --target <bastion instance id> \\
    --document-name AWS-StartPortForwardingSessionToRemoteHost \\
    --parameters '{"host":["<rds endpoint>"],"portNumber":["5432"],"localPortNumber":["5432"]}'

Needs the local `session-manager-plugin` (see infra/cdk/session-manager-plugin.deb).
"""
from __future__ import annotations

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_rds as rds
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

        # Not scoped to each consumer's own Lambda security group (unlike db_security_group
        # below): every Lambda that needs it lives in this same VPC's private subnets, so
        # opening 443 to the VPC CIDR is no broader than the actual set of callers, and it
        # avoids the same cross-stack ingress-rule dance StorefrontStack does for RDS.
        self.vpc_endpoints_security_group = ec2.SecurityGroup(
            self, "VpcEndpointsSecurityGroup", vpc=self.vpc,
            description="AWS service VPC interface endpoints: HTTPS from inside this VPC only",
            allow_all_outbound=False,
        )
        self.vpc_endpoints_security_group.add_ingress_rule(
            ec2.Peer.ipv4(self.vpc.vpc_cidr_block), ec2.Port.tcp(443),
            "HTTPS from VPC-placed Lambdas to AWS service endpoints",
        )
        self.secrets_manager_endpoint = self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.vpc_endpoints_security_group],
        )
        # Same rationale as SecretsManagerEndpoint: lets VPC-placed Lambdas call sqs:SendMessage
        # (order-status-change notifications, see NotificationsStack) without a NAT gateway. The
        # Lambda that actually sends the email stays outside the VPC entirely and doesn't need
        # this — only the DB-touching producers (storefront/admin_api's `orders` functions) do.
        self.sqs_endpoint = self.vpc.add_interface_endpoint(
            "SqsEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SQS,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[self.vpc_endpoints_security_group],
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

        # Just a named grouping of subnet IDs - unlike a `DatabaseInstance`, CDK can't force a
        # destructive replacement of the live RDS instance through this, so it's safe to manage
        # here even though that instance itself is created by hand (see module docstring).
        # Select this group when creating it in the console.
        self.db_subnet_group = rds.SubnetGroup(
            self, "RdsSubnetGroup", vpc=self.vpc,
            description="Storefront Postgres (RDS) subnet group",
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
        )

        bastion_security_group = ec2.SecurityGroup(
            self, "BastionSecurityGroup", vpc=self.vpc,
            description="DB bastion: reached only via SSM Session Manager, no SSH inbound",
            allow_all_outbound=True,
        )
        self.db_security_group.add_ingress_rule(
            bastion_security_group, ec2.Port.tcp(5432), "DB bastion (SSM) to Postgres",
        )

        bastion_role = iam.Role(
            self, "BastionRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore"),
            ],
        )
        self.bastion = ec2.Instance(
            self, "DbBastion",
            vpc=self.vpc,
            # The Public subnet's `mapPublicIpOnLaunch` (CDK's default for SubnetType.PUBLIC)
            # already gives every instance here a public IP with no per-instance opt-in — that's
            # the route to SSM's endpoints this VPC has no NAT gateway to otherwise provide. See
            # module docstring for why that public IP doesn't actually open anything up.
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.NANO),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            role=bastion_role,
            security_group=bastion_security_group,
        )

        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
        CfnOutput(self, "PrivateSubnetIds", value=",".join(private_subnet_ids))
        CfnOutput(self, "RdsSecurityGroupId", value=self.db_security_group.security_group_id)
        CfnOutput(self, "DbSubnetGroupName", value=self.db_subnet_group.subnet_group_name)
        CfnOutput(self, "BastionInstanceId", value=self.bastion.instance_id)
