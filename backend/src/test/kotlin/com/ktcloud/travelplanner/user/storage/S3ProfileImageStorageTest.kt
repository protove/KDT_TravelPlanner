package com.ktcloud.travelplanner.user.storage

import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import com.sun.net.httpserver.HttpServer
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.net.InetSocketAddress
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertNull
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

	@Test
	fun `reads uploaded object metadata through configured S3 endpoint`() {
		withStorageServer(
			status = 200,
			contentType = "image/png",
			contentLength = 1024,
		) { storage, requestedPaths ->
			val metadata = storage.getObjectMetadata("users/user-id/profile/image.png")

			assertEquals(ProfileImageObjectMetadata("image/png", 1024), metadata)
			assertEquals(listOf("/profile-images/users/user-id/profile/image.png"), requestedPaths)
		}
	}

	@Test
	fun `maps missing uploaded objects to an empty metadata result`() {
		withStorageServer(status = 404) { storage, requestedPaths ->
			assertNull(storage.getObjectMetadata("users/user-id/profile/missing.png"))
			assertEquals(listOf("/profile-images/users/user-id/profile/missing.png"), requestedPaths)
		}
	}

	@Test
	fun `maps storage authorization and server failures to external storage errors`() {
		listOf(403, 500).forEach { status ->
			withStorageServer(status = status) { storage, _ ->
				assertThrows<ProfileImageStorageException> {
					storage.getObjectMetadata("users/user-id/profile/image.png")
				}
			}
		}
	}

	private fun withStorageServer(
		status: Int,
		contentType: String? = null,
		contentLength: Long? = null,
		assertions: (S3ProfileImageStorage, List<String>) -> Unit,
	) {
		val requestedPaths = mutableListOf<String>()
		val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
		server.createContext("/") { exchange ->
			requestedPaths += exchange.requestURI.path
			if (contentType != null) {
				exchange.responseHeaders.set("Content-Type", contentType)
			}
			if (contentLength != null) {
				exchange.responseHeaders.set("Content-Length", contentLength.toString())
			}
			exchange.sendResponseHeaders(status, -1)
			exchange.close()
		}
		server.start()
		val storage = S3ProfileImageStorage(
			ProfileImageStorageProperties(
				enabled = true,
				endpoint = "http://127.0.0.1:${server.address.port}",
				region = "ap-northeast-2",
				accessKey = "test-access-key",
				secretKey = "test-secret-key",
				bucket = "profile-images",
				pathStyleAccessEnabled = true,
			),
		)
		try {
			assertions(storage, requestedPaths)
		} finally {
			storage.close()
			server.stop(0)
		}
	}
}
