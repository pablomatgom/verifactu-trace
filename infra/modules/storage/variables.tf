variable "project_name" {
  description = "Name of the project; it prefixes the name of every resource."
  type        = string
}

variable "availability_zone" {
  description = "Zone where the volume is created. It has to be the zone of the instance it is attached to: a volume cannot be attached across zones."
  type        = string
}

variable "size_gb" {
  description = "Size of the volume, in GB."
  type        = number
  default     = 10

  validation {
    condition     = var.size_gb >= 1
    error_message = "The volume needs at least 1 GB."
  }
}
