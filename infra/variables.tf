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

variable "admin_cidr_blocks" {
  description = "Addresses that can reach port 22 (SSH). Empty: no administration port is open."
  type        = list(string)
  default     = []
}

variable "data_volume_size_gb" {
  description = "Size, in GB, of the disk that keeps the data of PostgreSQL."
  type        = number
  default     = 10
}

# Sensitive and without a default value: it is never written in the code. It is passed with
# the TF_VAR_db_password environment variable and used by the compute layer, which gives it to
# the PostgreSQL container.
variable "db_password" {
  description = "Password of the database administrator."
  type        = string
  sensitive   = true
}
