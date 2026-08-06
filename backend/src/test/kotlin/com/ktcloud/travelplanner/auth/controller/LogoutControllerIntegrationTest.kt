package com.ktcloud.travelplanner.auth.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.auth.service.OAuthExchangeCodeService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.mock.web.MockCookie
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.time.Duration
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class LogoutControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val exchangeCodeService: OAuthExchangeCodeService,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@Test
	fun `logout revokes refresh token expires Cookie and remains idempotent`() {
		val authentication = login()

		val expiredCookie = logout(authentication)
		assertEquals("", expiredCookie.value)
		assertEquals(Duration.ZERO.seconds.toInt(), expiredCookie.maxAge)
		assertEquals(RefreshTokenCookieFactory.COOKIE_PATH, expiredCookie.path)
		assertEquals("Lax", expiredCookie.sameSite)
		assertTrue(expiredCookie.isHttpOnly)

		mockMvc.post("/api/v1/auth/token/refresh") {
			cookie(authentication.refreshCookie)
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}

		logout(authentication)
		logout(authentication, includeRefreshCookie = false)
	}

	@Test
	fun `logout with rotated token ancestor revokes current family token`() {
		val authentication = login()
		val refreshResponse = mockMvc.post("/api/v1/auth/token/refresh") {
			cookie(authentication.refreshCookie)
		}
			.andExpect {
				status { isOk() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
		val rotatedCookie = MockCookie.parse(
			requireNotNull(refreshResponse.response.getHeader(HttpHeaders.SET_COOKIE)),
		)

		logout(authentication)

		mockMvc.post("/api/v1/auth/token/refresh") {
			cookie(rotatedCookie)
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}
	}

	@Test
	fun `logout requires valid access token`() {
		mockMvc.post("/api/v1/auth/logout")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun login(): AuthenticationFixture {
		val user = userRepository.saveAndFlush(
			User(
				provider = OAuthProvider.GOOGLE,
				providerUserId = "logout-${UUID.randomUUID()}",
				email = "logout@example.com",
				name = "Logout User",
			),
		)
		val code = exchangeCodeService.issue(requireNotNull(user.id))
		val response = mockMvc.post("/api/v1/auth/token/exchange") {
			contentType = MediaType.APPLICATION_JSON
			content = objectMapper.writeValueAsString(mapOf("code" to code))
		}
			.andExpect { status { isOk() } }
			.andReturn()
			.response
		val accessToken = objectMapper.readTree(response.contentAsByteArray)
			.at("/data/accessToken")
			.asText()
		val refreshCookie = MockCookie.parse(
			requireNotNull(response.getHeader(HttpHeaders.SET_COOKIE)),
		)
		return AuthenticationFixture(accessToken, refreshCookie)
	}

	private fun logout(
		authentication: AuthenticationFixture,
		includeRefreshCookie: Boolean = true,
	): MockCookie {
		val response = mockMvc.post("/api/v1/auth/logout") {
			header(HttpHeaders.AUTHORIZATION, "Bearer ${authentication.accessToken}")
			if (includeRefreshCookie) {
				cookie(authentication.refreshCookie)
			}
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data") { exists() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
			.response
		return MockCookie.parse(requireNotNull(response.getHeader(HttpHeaders.SET_COOKIE)))
	}

	private data class AuthenticationFixture(
		val accessToken: String,
		val refreshCookie: MockCookie,
	)
}
