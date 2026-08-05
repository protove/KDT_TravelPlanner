package com.ktcloud.travelplanner.user.dto

import jakarta.validation.constraints.NotBlank

data class ProfileImageUploadCompleteRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	val objectKey: String,
)
