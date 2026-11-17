variable "project_name" {
  description = "Name of the project; it prefixes the name of every resource."
  type        = string
}

variable "aws_region" {
  description = "Region of the instance. The instance reads the database password from it."
  type        = string
}

variable "subnet_id" {
  description = "Public subnet where the instance is created."
  type        = string
}

variable "security_group_id" {
  description = "Security group of the instance."
  type        = string
}

variable "volume_id" {
  description = "Disk with the data of PostgreSQL. It has to be in the zone of the subnet."
  type        = string
}

variable "db_password" {
  description = "Password of the database. It is kept in Parameter Store, and the instance reads it from there when it boots."
  type        = string
  sensitive   = true
}

variable "db_user" {
  description = "User of the database."
  type        = string
  default     = "verifactu"
}

variable "db_name" {
  description = "Name of the database."
  type        = string
  default     = "verifactu"
}

# The images are built for amd64 only, so the instance has to be x86 (t3), not ARM (t4g).
variable "instance_type" {
  description = "Type of the instance. It runs five containers, so it needs about 2 GB of memory."
  type        = string
  default     = "t3.small"
}

variable "root_volume_size_gb" {
  description = "Size, in GB, of the disk of the instance (the system, Docker and the images)."
  type        = number
  default     = 20
}

variable "image_registry" {
  description = "Where the images of the services are published."
  type        = string
  default     = "ghcr.io/pablomatgom/verifactu-trace"
}

variable "image_tag" {
  description = "Tag of the images to run."
  type        = string
  default     = "latest"
}
