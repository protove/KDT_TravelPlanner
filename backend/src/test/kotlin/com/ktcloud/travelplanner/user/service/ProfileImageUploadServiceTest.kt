package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadCompleteRequest
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest
import com.ktcloud.travelplanner.user.dto.UserProfileResponse
import com.ktcloud.travelplanner.user.storage.ProfileImageObjectMetadata
import com.ktcloud.travelplanner.user.storage.ProfileImageStorage
import com.ktcloud.travelplanner.user.storage.ProfileImageStorageUnavailableException
import com.ktcloud.travelplanner.user.storage.ProfileImageUploadCommand
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.net.URI
import java.time.Duration
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ProfileImageUploadServiceTest {
	private val storage = RecordingProfileImageStorage()
	private val userProfileService = mock(UserProfileService::class.java)
	private val properties = ProfileImageStorageProperties(
		publicBaseUrl = "https://images.example/",
		uploadUrlTtl = Duration.ofMinutes(10),
	)
	private val service = ProfileImageUploadService(storage, properties, userProfileService, TestFixtures.FIXED_CLOCK)

	@Test
	fun `creates user-owned object keys for supported image formats`() {
		mapOf(
			"image/jpeg" to ".jpg",
			"image/png" to ".png",
			"image/webp" to ".webp",
		).forEach { (contentType, expectedSuffix) ->
			val response = service.createUploadUrl(
				TestFixtures.USER_ID,
				ProfileImageUploadUrlRequest(contentType, 1024),
			)

			assertTrue(response.objectKey.startsWith("users/${TestFixtures.USER_ID}/profile/"))
			assertTrue(response.objectKey.endsWith(expectedSuffix))
			assertEquals(response.objectKey, storage.lastCommand?.objectKey)
			assertEquals(contentType, storage.lastCommand?.contentType)
		}
	}

	@Test
	fun `maps storage URL size and deterministic expiration`() {
		val response = service.createUploadUrl(
			TestFixtures.USER_ID,
			ProfileImageUploadUrlRequest("image/png", 5L * 1024 * 1024),
		)

		assertEquals(URI.create("https://storage.example/upload"), response.uploadUrl)
		assertEquals(TestFixtures.FIXED_INSTANT.plus(Duration.ofMinutes(10)), response.expiresAt)
		assertEquals(5L * 1024 * 1024, storage.lastCommand?.fileSize)
		assertEquals(Duration.ofMinutes(10), storage.lastCommand?.expiresIn)
	}

	@Test
	fun `rejects unsupported type and invalid file size before storage`() {
		assertThrows<InvalidProfileImageException> {
			service.createUploadUrl(
				TestFixtures.USER_ID,
				ProfileImageUploadUrlRequest("image/gif", 1024),
			)
		}
		assertThrows<InvalidProfileImageException> {
			service.createUploadUrl(
				TestFixtures.USER_ID,
				ProfileImageUploadUrlRequest("image/jpeg", 5L * 1024 * 1024 + 1),
			)
		}
		assertEquals(0, storage.invocationCount)
	}

	@Test
	fun `completes an owned uploaded image with matching metadata`() {
		val objectKey = validObjectKey("webp")
		val expectedResponse = mock(UserProfileResponse::class.java)
		storage.objectMetadata = ProfileImageObjectMetadata("image/webp", 5L * 1024 * 1024)
		`when`(
			userProfileService.updateProfileImage(
				TestFixtures.USER_ID,
				"https://images.example/$objectKey",
			),
		).thenReturn(expectedResponse)

		val response = service.completeUpload(
			TestFixtures.USER_ID,
			ProfileImageUploadCompleteRequest(objectKey),
		)

		assertEquals(expectedResponse, response)
		assertEquals(objectKey, storage.lastMetadataObjectKey)
		verify(userProfileService).updateProfileImage(
			TestFixtures.USER_ID,
			"https://images.example/$objectKey",
		)
	}

	@Test
	fun `rejects unowned or malformed object keys before storage lookup`() {
		listOf(
			"users/${UUID.randomUUID()}/profile/${UUID.randomUUID()}.png",
			"users/${TestFixtures.USER_ID}/profile/not-a-uuid.png",
			"users/${TestFixtures.USER_ID}/profile/${UUID.randomUUID()}.gif",
			"users/${TestFixtures.USER_ID}/profile/../${UUID.randomUUID()}.png",
		).forEach { objectKey ->
			assertThrows<InvalidProfileImageException> {
				service.completeUpload(
					TestFixtures.USER_ID,
					ProfileImageUploadCompleteRequest(objectKey),
				)
			}
		}

		assertEquals(0, storage.metadataInvocationCount)
		verifyNoInteractions(userProfileService)
	}

	@Test
	fun `rejects missing and invalid uploaded object metadata`() {
		val objectKey = validObjectKey("png")
		storage.objectMetadata = null
		assertThrows<UploadedProfileImageNotFoundException> {
			service.completeUpload(TestFixtures.USER_ID, ProfileImageUploadCompleteRequest(objectKey))
		}

		listOf(
			ProfileImageObjectMetadata("image/jpeg", 1024),
			ProfileImageObjectMetadata("image/png", 0),
			ProfileImageObjectMetadata("image/png", 5L * 1024 * 1024 + 1),
			ProfileImageObjectMetadata(null, 1024),
		).forEach { metadata ->
			storage.objectMetadata = metadata
			assertThrows<InvalidProfileImageException> {
				service.completeUpload(TestFixtures.USER_ID, ProfileImageUploadCompleteRequest(objectKey))
			}
		}

		verifyNoInteractions(userProfileService)
	}

	@Test
	fun `rejects completion when public image base URL is unavailable`() {
		val objectKey = validObjectKey("jpg")
		storage.objectMetadata = ProfileImageObjectMetadata("image/jpeg", 1024)
		val unavailableService = ProfileImageUploadService(
			storage,
			ProfileImageStorageProperties(publicBaseUrl = "storage-without-scheme"),
			userProfileService,
			TestFixtures.FIXED_CLOCK,
		)

		assertThrows<ProfileImageStorageUnavailableException> {
			unavailableService.completeUpload(
				TestFixtures.USER_ID,
				ProfileImageUploadCompleteRequest(objectKey),
			)
		}
		verifyNoInteractions(userProfileService)
	}

	private fun validObjectKey(extension: String): String =
		"users/${TestFixtures.USER_ID}/profile/11111111-1111-4111-8111-111111111111.$extension"

	private class RecordingProfileImageStorage : ProfileImageStorage {
		var lastCommand: ProfileImageUploadCommand? = null
		var lastMetadataObjectKey: String? = null
		var objectMetadata: ProfileImageObjectMetadata? = null
		var invocationCount: Int = 0
		var metadataInvocationCount: Int = 0

		override fun createUploadUrl(command: ProfileImageUploadCommand): URI {
			lastCommand = command
			invocationCount++
			return URI.create("https://storage.example/upload")
		}

		override fun getObjectMetadata(objectKey: String): ProfileImageObjectMetadata? {
			lastMetadataObjectKey = objectKey
			metadataInvocationCount++
			return objectMetadata
		}
	}
}
