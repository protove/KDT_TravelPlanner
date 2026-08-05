variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name used for Terraform state."

  validation {
    condition     = length(var.bucket_name) >= 3 && length(var.bucket_name) <= 63 && can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]$", var.bucket_name))
    error_message = "bucket_name must be a valid 3-63 character lowercase S3 bucket name."
  }
}

variable "state_keys" {
  type        = set(string)
  description = "Terraform state object keys that day-to-day operators may read and update."

  validation {
    condition     = length(var.state_keys) > 0 && alltrue([for key in var.state_keys : length(trimspace(key)) > 0 && !startswith(key, "/")])
    error_message = "state_keys must contain non-empty relative object keys."
  }
}

variable "tags" {
  type        = map(string)
  description = "Tags applied to the Terraform state bucket."
  default     = {}
}
