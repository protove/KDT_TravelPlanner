variable "bucket_name" {
  description = "S3 버킷 이름 (전 세계에서 고유해야 함)"
  type        = string
}

variable "allowed_origins" {
  description = "S3에 직접 업로드를 허용할 프론트 도메인 목록"
  type        = list(string)
  default     = ["http://localhost:3000"]
}
