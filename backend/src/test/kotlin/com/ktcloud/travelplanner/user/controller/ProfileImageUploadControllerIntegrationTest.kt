package com.ktcloud.travelplanner.user.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import com.ktcloud.travelplanner.user.storage.ProfileImageObjectMetadata
import com.ktcloud.travelplanner.user.storage.ProfileImageStorage
import com.ktcloud.travelplanner.user.storage.ProfileImageUploadCommand
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.matchesPattern
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Import
import org.springframework.context.annotation.Primary
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.net.URI
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class, FakeProfileImageStorageConfiguration::class)
@Transactional
class ProfileImageUploadControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val fakeProfileImageStorage: FakeProfileImageStorage,
) {
	@BeforeEach
	fun resetFakeStorage() {
		fakeProfileImageStorage.reset()
	}

	@Test
	fun `authenticated user receives upload URL from fake storage`() {
		val user = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.post("/api/v1/users/me/profile-image/upload-url") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"contentType":"image/webp","fileSize":5242880}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.uploadUrl", equalTo("https://storage.test/upload"))
				jsonPath(
					"$.data.objectKey",
					matchesPattern("users/${user.id}/profile/[0-9a-f-]{36}\\.webp"),
				)
				jsonPath("$.data.expiresAt") { exists() }
			}

		val command = assertNotNull(fakeProfileImageStorage.lastCommand)
		assertEquals("image/webp", command.contentType)
		assertEquals(5L * 1024 * 1024, command.fileSize)
		assertEquals("users/${user.id}/profile/", command.objectKey.substringBeforeLast('/') + "/")
	}

	@Test
	fun `invalid file requests return validation errors without invoking storage`() {
		val user = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.post("/api/v1/users/me/profile-image/upload-url") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"contentType":"image/gif","fileSize":5242881}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("contentType"))
				jsonPath("$.fieldErrors[1].field", equalTo("fileSize"))
			}

		assertEquals(0, fakeProfileImageStorage.invocationCount)
	}

	@Test
	fun `unauthenticated upload URL request is rejected`() {
		mockMvc.post("/api/v1/users/me/profile-image/upload-url") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"contentType":"image/jpeg","fileSize":1024}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `authenticated user completes upload and persists public profile image URL`() {
		val user = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value
		val objectKey = "users/${user.id}/profile/11111111-1111-4111-8111-111111111111.webp"
		fakeProfileImageStorage.objectMetadata = ProfileImageObjectMetadata("image/webp", 1024)

		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":"$objectKey"}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.userId", equalTo(user.id.toString()))
				jsonPath("$.data.profileImageUrl", equalTo("https://images.test/$objectKey"))
			}

		assertEquals(objectKey, fakeProfileImageStorage.lastMetadataObjectKey)
		assertEquals(
			"https://images.test/$objectKey",
			userRepository.findById(requireNotNull(user.id)).orElseThrow().profileImageUrl,
		)
	}

	@Test
	fun `completion rejects missing invalid and unowned objects without changing profile`() {
		val user = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value
		val objectKey = "users/${user.id}/profile/11111111-1111-4111-8111-111111111111.png"

		fakeProfileImageStorage.objectMetadata = null
		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":"$objectKey"}"""
		}
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}

		fakeProfileImageStorage.objectMetadata = ProfileImageObjectMetadata("image/jpeg", 1024)
		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":"$objectKey"}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}

		val metadataInvocations = fakeProfileImageStorage.metadataInvocationCount
		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":"users/${UUID.randomUUID()}/profile/11111111-1111-4111-8111-111111111111.png"}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}

		assertEquals(metadataInvocations, fakeProfileImageStorage.metadataInvocationCount)
		assertEquals(null, userRepository.findById(requireNotNull(user.id)).orElseThrow().profileImageUrl)
	}

	@Test
	fun `unauthenticated completion request is rejected`() {
		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":"users/${UUID.randomUUID()}/profile/11111111-1111-4111-8111-111111111111.png"}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `blank completion object key returns validation error without invoking storage`() {
		val user = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.post("/api/v1/users/me/profile-image/complete") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"objectKey":""}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("objectKey"))
			}

		assertEquals(0, fakeProfileImageStorage.metadataInvocationCount)
	}

	private fun saveUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "profile-image-${UUID.randomUUID()}",
		),
	)
}

@TestConfiguration(proxyBeanMethods = false)
class FakeProfileImageStorageConfiguration {
	@Bean
	@Primary
	fun fakeProfileImageStorage(): FakeProfileImageStorage = FakeProfileImageStorage()
}

class FakeProfileImageStorage : ProfileImageStorage {
	var lastCommand: ProfileImageUploadCommand? = null
	var lastMetadataObjectKey: String? = null
	var objectMetadata: ProfileImageObjectMetadata? = null
	var invocationCount: Int = 0
	var metadataInvocationCount: Int = 0

	override fun createUploadUrl(command: ProfileImageUploadCommand): URI {
		lastCommand = command
		invocationCount++
		return URI.create("https://storage.test/upload")
	}

	override fun getObjectMetadata(objectKey: String): ProfileImageObjectMetadata? {
		lastMetadataObjectKey = objectKey
		metadataInvocationCount++
		return objectMetadata
	}

	fun reset() {
		lastCommand = null
		lastMetadataObjectKey = null
		objectMetadata = null
		invocationCount = 0
		metadataInvocationCount = 0
	}
}
