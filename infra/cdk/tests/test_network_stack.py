"""CDK assertions for NetworkStack (VPC, subnets, RDS security group)."""
from __future__ import annotations

from aws_cdk.assertions import Match, Template

from .conftest import synth_stacks


def _synth() -> Template:
    network_stack, _, _ = synth_stacks()
    return Template.from_stack(network_stack)


def test_creates_one_vpc():
    template = _synth()
    template.resource_count_is("AWS::EC2::VPC", 1)


def test_no_nat_gateway():
    template = _synth()
    template.resource_count_is("AWS::EC2::NatGateway", 0)


def test_creates_public_and_private_subnets():
    template = _synth()
    # 2 AZs x (1 public + 1 private) subnet.
    subnets = template.find_resources("AWS::EC2::Subnet")
    assert len(subnets) == 4


def test_creates_the_rds_security_group():
    template = _synth()
    # StorefrontStack adds the actual tcp/5432 ingress rule from its Lambda security group —
    # see test_storefront_stack.py — so this only checks the group itself exists here.
    template.has_resource_properties(
        "AWS::EC2::SecurityGroup",
        {"GroupDescription": Match.string_like_regexp("Storefront Postgres")},
    )
