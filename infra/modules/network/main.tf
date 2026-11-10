data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # Both subnets are in the first zone of the region.
  az = data.aws_availability_zones.available.names[0]

  # One rule per port and per address, because a rule has a single port and a single range.
  app_rules = {
    for pair in setproduct(var.app_ports, var.app_allowed_cidr_blocks) :
    "${pair[0]}-${pair[1]}" => { port = pair[0], cidr = pair[1] }
  }
}

# --- Network and exit to the Internet -------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  # Needed to resolve names inside the network.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project_name}-igw" }
}

# --- Subnets --------------------------------------------------------------------------------

# Public: its route table sends the Internet traffic through the gateway. The instance that
# lives here asks for its own public address; the subnet does not hand it out by default.
resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.public_subnet_cidr
  availability_zone = local.az

  tags = { Name = "${var.project_name}-public" }
}

# Private: no route to the Internet, in either direction. Nothing runs here yet: the
# database is a container of the compute instance. It is kept for what must never be
# reachable from outside (for example, a managed database in the future).
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidr
  availability_zone = local.az

  tags = { Name = "${var.project_name}-private" }
}

# --- Routing --------------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Without routes of its own, it only knows the addresses inside the network.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project_name}-private" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# --- Security groups ------------------------------------------------------------------------

# AWS creates a default group in every VPC, and it lets its members talk to each other. A
# resource created without naming a group would land in it. Declaring it with no rules makes
# Terraform remove all of them, so whatever ends up there cannot send or receive anything.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${var.project_name}-default-unused" }
}

# --- Security group of the compute instance -------------------------------------------------

# PostgreSQL and Redis are containers of the instance and talk to the services inside it, so
# their ports are not opened here: only the ports of the application are.
resource "aws_security_group" "compute" {
  name        = "${var.project_name}-compute"
  description = "Compute instance: the ports of the application"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-compute" }
}

resource "aws_vpc_security_group_ingress_rule" "app" {
  for_each = local.app_rules

  security_group_id = aws_security_group.compute.id
  description       = "Application port ${each.value.port}"
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  cidr_ipv4         = each.value.cidr
}

resource "aws_vpc_security_group_ingress_rule" "admin" {
  for_each = toset(var.admin_cidr_blocks)

  security_group_id = aws_security_group.compute.id
  description       = "Administration (SSH)"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = each.value
}

# The instance has to go out: to pull the images and to resolve names.
resource "aws_vpc_security_group_egress_rule" "compute_all" {
  security_group_id = aws_security_group.compute.id
  description       = "All the outgoing traffic"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
