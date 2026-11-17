locals {
  # Docker Compose is not in the repositories of Amazon Linux, so the instance downloads it.
  # The version and the checksum are fixed: to update it, take the new tag and the SHA-256 of
  # docker-compose-linux-x86_64 from https://github.com/docker/compose/releases.
  compose_version = "v5.7.0"
  compose_sha256  = "7758048ad38e580f22559603312874fec8bb638d021a9e64182385fc17cc12a2"

  password_parameter = "/${var.project_name}/db-password"
}

# --- Image of the system --------------------------------------------------------------------

# The latest Amazon Linux 2023 for x86. The provider marks every Parameter Store value as
# sensitive, but an image identifier is not a secret, so `nonsensitive` shows it in the plan.
# `ami` is ignored in the instance, so a newer image does not replace a running instance.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# --- The password ---------------------------------------------------------------------------

# The password is not written in the user data, which anybody who can describe the instance
# can read. The instance fetches it from here when it boots, with a permission that only
# allows reading this parameter.
resource "aws_ssm_parameter" "db_password" {
  name  = local.password_parameter
  type  = "SecureString"
  value = var.db_password
}

# --- Permissions of the instance ------------------------------------------------------------

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project_name}-app"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

# Lets AWS Systems Manager open a session on the instance, so there is no need to open the
# SSH port or to keep keys.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "read_password" {
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.db_password.arn]
  }
}

resource "aws_iam_role_policy" "read_password" {
  name   = "read-db-password"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_password.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-app"
  role = aws_iam_role.app.name
}

# --- The instance ---------------------------------------------------------------------------

resource "aws_instance" "app" {
  ami                    = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  # The subnet does not hand out public addresses by itself: the instance asks for one.
  associate_public_ip_address = true

  # Runs once, on the first boot. A change in the script replaces the instance.
  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    aws_region         = var.aws_region
    compose_version    = local.compose_version
    compose_sha256     = local.compose_sha256
    compose_b64        = base64encode(file("${path.module}/files/compose.yaml"))
    init_sql_b64       = base64encode(file("${path.root}/../db/init/01-schemas.sql"))
    volume_device_id   = replace(var.volume_id, "-", "")
    password_parameter = local.password_parameter
    db_user            = var.db_user
    db_name            = var.db_name
    image_registry     = var.image_registry
    image_tag          = var.image_tag
  })
  user_data_replace_on_change = true

  # IMDSv2 only: a request to the metadata service needs a token, which blocks the theft of
  # credentials through a server-side request forgery.
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
    encrypted   = true
  }

  tags = { Name = "${var.project_name}-app" }

  # The instance reads the password as soon as it boots, so the permission has to exist before.
  depends_on = [aws_iam_role_policy.read_password]

  lifecycle {
    ignore_changes = [ami]
  }
}

# The disk with the data of PostgreSQL. Stopping the instance before detaching lets the system
# unmount it cleanly; otherwise `terraform destroy` waits for a disk that is still in use.
resource "aws_volume_attachment" "postgres_data" {
  device_name                    = "/dev/sdf"
  volume_id                      = var.volume_id
  instance_id                    = aws_instance.app.id
  stop_instance_before_detaching = true
}
