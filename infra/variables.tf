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

# Sensitive and without a default value: it is never written in the code. It is passed with
# the TF_VAR_db_password environment variable and used by the storage layer.
variable "db_password" {
  description = "Password of the database administrator."
  type        = string
  sensitive   = true
}
