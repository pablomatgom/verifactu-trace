variable "project_name" {
  description = "Name of the project; it prefixes the name of every resource."
  type        = string
  default     = "verifactu-trace"
}

variable "aws_region" {
  description = "AWS region where everything is created. It must be in the European Union (GDPR)."
  type        = string
  default     = "eu-north-1"

  validation {
    condition     = startswith(var.aws_region, "eu-")
    error_message = "The region must be one of the European Union (eu-*)."
  }
}

variable "app_ports" {
  description = "TCP ports of the application that are open to the Internet. Today, the ones of the three services; they become the single port of the gateway."
  type        = list(number)
  default     = [8001, 8002, 8003]
}

variable "app_allowed_cidr_blocks" {
  description = "Addresses that can reach the ports of the application."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "data_volume_size_gb" {
  description = "Size, in GB, of the disk that keeps the data of PostgreSQL."
  type        = number
  default     = 10
}

variable "instance_type" {
  description = "Type of the instance that runs the containers. It has to be x86: the images are built for amd64 only."
  type        = string
  default     = "t3.small"
}

variable "image_tag" {
  description = "Tag of the images of the services to run."
  type        = string
  default     = "latest"
}

# Sensitive and without a default value: it is never written in the code. It is passed with
# the TF_VAR_db_password environment variable and used by the compute layer, which gives it to
# the PostgreSQL container.
variable "db_password" {
  description = "Password of the database administrator."
  type        = string
  sensitive   = true

  # Letters and digits only: the password goes into an .env file, where characters such as
  # $, # or quotes would be read as something else.
  validation {
    condition     = length(var.db_password) >= 12 && can(regex("^[A-Za-z0-9]+$", var.db_password))
    error_message = "The password needs at least 12 characters, and only letters and digits."
  }
}
