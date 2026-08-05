package com.ktcloud.travelplanner.user.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.Gender
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class UserProfileControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `authenticated user gets own profile`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.get("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.userId", equalTo(user.id.toString()))
				jsonPath("$.data.provider", equalTo("NAVER"))
				jsonPath("$.data.email", equalTo("profile@example.com"))
				jsonPath("$.data.name", equalTo("Profile User"))
				jsonPath("$.data.nickname", equalTo("traveler"))
				jsonPath("$.data.profileImageUrl", equalTo("https://images.example/profile.png"))
				jsonPath("$.data.gender", equalTo("OTHER"))
				jsonPath("$.data.birthYear", equalTo(2001))
				jsonPath("$.data.isProfileCompleted", equalTo(true))
			}
	}

	@Test
	fun `unauthenticated and deleted users cannot get profile`() {
		mockMvc.get("/api/v1/users/me/profile")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}

		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value
		user.softDelete(TestFixtures.FIXED_INSTANT)
		userRepository.saveAndFlush(user)
		entityManager.clear()

		mockMvc.get("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `authenticated user partially updates own profile`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"nickname":"updatedTraveler"}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.nickname", equalTo("updatedTraveler"))
				jsonPath("$.data.profileImageUrl", equalTo("https://images.example/profile.png"))
				jsonPath("$.data.gender", equalTo("OTHER"))
				jsonPath("$.data.birthYear", equalTo(2001))
				jsonPath("$.data.isProfileCompleted", equalTo(true))
			}

		entityManager.flush()
		entityManager.clear()
		val updatedUser = userRepository.findById(requireNotNull(user.id)).orElseThrow()
		kotlin.test.assertEquals("updatedTraveler", updatedUser.nickname)
		kotlin.test.assertEquals(Gender.OTHER, updatedUser.gender)
		kotlin.test.assertEquals(2001.toShort(), updatedUser.birthYear)
	}

	@Test
	fun `non-null profile image URL is rejected without changing profile`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"profileImageUrl":"https://unverified.example/image.png"}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("profileImageUrl"))
			}

		entityManager.clear()
		kotlin.test.assertEquals(
			"https://images.example/profile.png",
			userRepository.findById(requireNotNull(user.id)).orElseThrow().profileImageUrl,
		)
	}

	@Test
	fun `explicit null clears profile fields and omitted fields remain unchanged`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"profileImageUrl":null,"gender":null,"birthYear":null}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.nickname", equalTo("traveler"))
				jsonPath("$.data.profileImageUrl") { doesNotExist() }
				jsonPath("$.data.gender") { doesNotExist() }
				jsonPath("$.data.birthYear") { doesNotExist() }
				jsonPath("$.data.isProfileCompleted", equalTo(true))
			}
	}

	@Test
	fun `duplicate nickname returns conflict without changing profile`() {
		val existingUser = saveCompletedUser("existing-profile")
		val user = saveCompletedUser("profile-to-update", "anotherTraveler")
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"nickname":"${existingUser.nickname}"}"""
		}
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
				jsonPath("$.message", equalTo("이미 사용 중인 닉네임입니다."))
			}

		entityManager.clear()
		kotlin.test.assertEquals(
			"anotherTraveler",
			userRepository.findById(requireNotNull(user.id)).orElseThrow().nickname,
		)
	}

	@Test
	fun `invalid profile fields return sorted validation errors`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"nickname":" ","birthYear":1899}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("birthYear"))
				jsonPath("$.fieldErrors[1].field", equalTo("nickname"))
			}
	}

	@Test
	fun `unsupported gender and missing authentication are rejected`() {
		val user = saveCompletedUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(user.id)).value

		mockMvc.patch("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"gender":"UNKNOWN"}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("MALFORMED_JSON"))
			}

		mockMvc.patch("/api/v1/users/me/profile") {
			contentType = MediaType.APPLICATION_JSON
			content = "{}"
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun saveCompletedUser(
		providerUserId: String = "profile-${UUID.randomUUID()}",
		nickname: String = "traveler",
	): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.NAVER,
			providerUserId = providerUserId,
			email = "profile@example.com",
			name = "Profile User",
		).also {
			it.updateOAuthProfile(
				email = "profile@example.com",
				name = "Profile User",
				profileImageUrl = "https://images.example/profile.png",
			)
			it.completeProfile(
				nickname = nickname,
				gender = Gender.OTHER,
				birthYear = 2001,
			)
		},
	)
}
