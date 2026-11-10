variable "project_name" {
  description = "Name of the project; it prefixes the name of every resource."
  type        = string
}

variable "vpc_cidr" {
  description = "Address range of the whole network."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Address range of the public subnet, where the compute instance lives."
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  description = "Address range of the private subnet, which has no route to the Internet."
  type        = string
  default     = "10.0.2.0/24"
}

variable "app_ports" {
  description = "TCP ports of the application that are open to app_allowed_cidr_blocks."
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
