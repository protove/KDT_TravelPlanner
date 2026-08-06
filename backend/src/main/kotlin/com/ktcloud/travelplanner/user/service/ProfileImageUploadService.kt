package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadCompleteRequest
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest.Companion.MAX_PROFILE_IMAGE_SIZE
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlResponse
import com.ktcloud.travelplanner.user.dto.UserProfileResponse
import com.ktcloud.travelplanner.user.storage.ProfileImageStorage
import com.ktcloud.travelplanner.user.storage.ProfileImageStorageUnavailableException
import com.ktcloud.travelplanner.user.storage.ProfileImageUploadCommand
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.stereotype.Service
import java.net.URI
import java.time.Clock
import java.time.Instant
import java.util.UUID

@Service
class ProfileImageUploadService(
	private val profileImageStorage: ProfileImageStorage,
	private val properties: ProfileImageStorageProperties,
	private val userProfileService: UserProfileService,
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

	fun completeUpload(
		userId: UUID,
		request: ProfileImageUploadCompleteRequest,
	): UserProfileResponse {
		val expectedContentType = getExpectedContentType(userId, request.objectKey)
		val metadata = profileImageStorage.getObjectMetadata(request.objectKey)
			?: throw UploadedProfileImageNotFoundException()
		if (metadata.contentType != expectedContentType || metadata.fileSize !in 1..MAX_PROFILE_IMAGE_SIZE) {
			throw InvalidProfileImageException()
		}

		return userProfileService.updateProfileImage(
			userId = userId,
			profileImageUrl = createPublicUrl(request.objectKey),
		)
	}

	private fun createObjectKey(
		userId: UUID,
		fileExtension: String,
	): String = "users/$userId/profile/${UUID.randomUUID()}.$fileExtension"

	private fun getExpectedContentType(
		userId: UUID,
		objectKey: String,
	): String {
		val ownedObjectPrefix = "users/$userId/profile/"
		if (!objectKey.startsWith(ownedObjectPrefix)) {
			throw InvalidProfileImageException()
		}
		val fileName = objectKey.removePrefix(ownedObjectPrefix)
		val match = PROFILE_IMAGE_FILE_PATTERN.matchEntire(fileName)
			?: throw InvalidProfileImageException()
		return EXTENSION_CONTENT_TYPES.getValue(match.groupValues[1])
	}

	private fun createPublicUrl(objectKey: String): String {
		val publicBaseUrl = properties.publicBaseUrl.trim().trimEnd('/')
		val baseUri = try {
			URI.create(publicBaseUrl)
		} catch (exception: IllegalArgumentException) {
			throw ProfileImageStorageUnavailableException()
		}
		if (
			publicBaseUrl.isBlank() ||
			!baseUri.isAbsolute ||
			baseUri.scheme !in PUBLIC_URL_SCHEMES ||
			baseUri.host.isNullOrBlank() ||
			baseUri.rawQuery != null ||
			baseUri.rawFragment != null
		) {
			throw ProfileImageStorageUnavailableException()
		}
		return "$publicBaseUrl/$objectKey"
	}

	companion object {
		private val CONTENT_TYPE_EXTENSIONS = mapOf(
			"image/jpeg" to "jpg",
			"image/png" to "png",
			"image/webp" to "webp",
		)
		private val EXTENSION_CONTENT_TYPES = CONTENT_TYPE_EXTENSIONS.entries.associate { (contentType, extension) ->
			extension to contentType
		}
		private val PROFILE_IMAGE_FILE_PATTERN = Regex(
			"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.(jpg|png|webp)",
		)
		private val PUBLIC_URL_SCHEMES = setOf("http", "https")
	}
}

class InvalidProfileImageException :
	DomainException(ErrorCode.INVALID_REQUEST, "프로필 이미지 파일 정보가 올바르지 않습니다.")

class UploadedProfileImageNotFoundException :
	DomainException(ErrorCode.RESOURCE_NOT_FOUND, "업로드된 프로필 이미지를 찾을 수 없습니다.")
