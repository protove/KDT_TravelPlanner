package com.ktcloud.travelplanner.user.storage

import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class S3ProfileImageStorageTest {
	@Test
	fun `creates path-style presigned PUT URL for configured S3-compatible storage`() {
		val storage = S3ProfileImageStorage(
			ProfileImageStorageProperties(
				enabled = true,
				endpoint = "http://localhost:9000",
				region = "ap-northeast-2",
				accessKey = "test-access-key",
				secretKey = "test-secret-key",
				bucket = "profile-images",
				pathStyleAccessEnabled = true,
			),
		)

		val uploadUrl = storage.createUploadUrl(
			ProfileImageUploadCommand(
				objectKey = "users/user-id/profile/image.png",
				contentType = "image/png",
				fileSize = 1024,
				expiresIn = Duration.ofMinutes(10),
			),
		)

		assertEquals("localhost", uploadUrl.host)
		assertEquals(9000, uploadUrl.port)
		assertEquals("/profile-images/users/user-id/profile/image.png", uploadUrl.path)
		assertTrue(uploadUrl.query.contains("X-Amz-Algorithm=AWS4-HMAC-SHA256"))
		assertTrue(uploadUrl.query.contains("X-Amz-Expires=600"))
		storage.close()
	}

	@Test
	fun `rejects upload URL creation when storage is disabled`() {
		val storage = S3ProfileImageStorage(ProfileImageStorageProperties())

		assertThrows<ProfileImageStorageUnavailableException> {
			storage.createUploadUrl(
				ProfileImageUploadCommand(
					objectKey = "users/user-id/profile/image.jpg",
					contentType = "image/jpeg",
					fileSize = 1024,
					expiresIn = Duration.ofMinutes(10),
				),
			)
		}
	}
}
