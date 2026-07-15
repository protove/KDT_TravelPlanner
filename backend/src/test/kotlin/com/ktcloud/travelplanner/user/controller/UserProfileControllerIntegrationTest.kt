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
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
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

	private fun saveCompletedUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.NAVER,
			providerUserId = "profile-${UUID.randomUUID()}",
			email = "profile@example.com",
			name = "Profile User",
		).also {
			it.updateOAuthProfile(
				email = "profile@example.com",
				name = "Profile User",
				profileImageUrl = "https://images.example/profile.png",
			)
			it.completeProfile(
				nickname = "traveler",
				gender = Gender.OTHER,
				birthYear = 2001,
			)
		},
	)
}
