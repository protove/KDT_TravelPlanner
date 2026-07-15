package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest.Companion.MAX_PROFILE_IMAGE_SIZE
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlResponse
import com.ktcloud.travelplanner.user.storage.ProfileImageStorage
import com.ktcloud.travelplanner.user.storage.ProfileImageUploadCommand
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.stereotype.Service
import java.time.Clock
import java.time.Instant
import java.util.UUID

@Service
class ProfileImageUploadService(
	private val profileImageStorage: ProfileImageStorage,
	private val properties: ProfileImageStorageProperties,
	@Qualifier("utcClock") private val clock: Clock,
) {
	fun createUploadUrl(
		userId: UUID,
		request: ProfileImageUploadUrlRequest,
	): ProfileImageUploadUrlResponse {
		val fileExtension = CONTENT_TYPE_EXTENSIONS[request.contentType]
			?: throw InvalidProfileImageException()
		if (request.fileSize !in 1..MAX_PROFILE_IMAGE_SIZE) {
			throw InvalidProfileImageException()
		}
		val objectKey = createObjectKey(userId, fileExtension)
		val expiresAt = Instant.now(clock).plus(properties.uploadUrlTtl)
		val uploadUrl = profileImageStorage.createUploadUrl(
			ProfileImageUploadCommand(
				objectKey = objectKey,
				contentType = request.contentType,
				fileSize = request.fileSize,
				expiresIn = properties.uploadUrlTtl,
			),
		)

		return ProfileImageUploadUrlResponse(
			uploadUrl = uploadUrl,
			objectKey = objectKey,
			expiresAt = expiresAt,
		)
	}

	private fun createObjectKey(
		userId: UUID,
		fileExtension: String,
	): String = "users/$userId/profile/${UUID.randomUUID()}.$fileExtension"

	companion object {
		private val CONTENT_TYPE_EXTENSIONS = mapOf(
			"image/jpeg" to "jpg",
			"image/png" to "png",
			"image/webp" to "webp",
		)
	}
}

class InvalidProfileImageException :
	DomainException(ErrorCode.INVALID_REQUEST, "프로필 이미지 파일 정보가 올바르지 않습니다.")
