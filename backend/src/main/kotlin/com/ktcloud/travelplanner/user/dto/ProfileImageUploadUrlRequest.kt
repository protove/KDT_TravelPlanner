package com.ktcloud.travelplanner.user.dto

import jakarta.validation.constraints.Max
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Pattern
import jakarta.validation.constraints.Positive

data class ProfileImageUploadUrlRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	@field:Pattern(
		regexp = "image/(jpeg|png|webp)",
		message = "JPEG, PNG, WebP 형식만 사용할 수 있습니다.",
	)
	val contentType: String,
	@field:Positive(message = "0보다 커야 합니다.")
	@field:Max(value = MAX_PROFILE_IMAGE_SIZE, message = "5MB 이하여야 합니다.")
	val fileSize: Long,
) {
	companion object {
		const val MAX_PROFILE_IMAGE_SIZE: Long = 5L * 1024 * 1024
	}
}
