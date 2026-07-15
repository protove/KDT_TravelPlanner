package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import com.ktcloud.travelplanner.user.dto.ProfileImageUploadUrlRequest
import com.ktcloud.travelplanner.user.storage.ProfileImageStorage
import com.ktcloud.travelplanner.user.storage.ProfileImageUploadCommand
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.net.URI
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ProfileImageUploadServiceTest {
	private val storage = RecordingProfileImageStorage()
	private val properties = ProfileImageStorageProperties(uploadUrlTtl = Duration.ofMinutes(10))
	private val service = ProfileImageUploadService(storage, properties, TestFixtures.FIXED_CLOCK)

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

	private class RecordingProfileImageStorage : ProfileImageStorage {
		var lastCommand: ProfileImageUploadCommand? = null
		var invocationCount: Int = 0

		override fun createUploadUrl(command: ProfileImageUploadCommand): URI {
			lastCommand = command
			invocationCount++
			return URI.create("https://storage.example/upload")
		}
	}
}
