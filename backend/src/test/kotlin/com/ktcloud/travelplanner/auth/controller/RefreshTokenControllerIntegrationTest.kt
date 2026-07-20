package com.ktcloud.travelplanner.auth.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.auth.repository.RedisRefreshTokenStore
import com.ktcloud.travelplanner.auth.repository.RefreshTokenHasher
import com.ktcloud.travelplanner.auth.repository.RefreshTokenStore
import com.ktcloud.travelplanner.auth.service.OAuthExchangeCodeService
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.data.redis.core.StringRedisTemplate
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
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class RefreshTokenControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val exchangeCodeService: OAuthExchangeCodeService,
	@Autowired private val refreshTokenStore: RefreshTokenStore,
	@Autowired private val refreshTokenHasher: RefreshTokenHasher,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val redisTemplate: StringRedisTemplate,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@BeforeEach
	fun clearRefreshTokens() {
		redisTemplate.keys("${RedisRefreshTokenStore.KEY_PREFIX}:*")
			.takeIf { it.isNotEmpty() }
			?.let(redisTemplate::delete)
	}

	@Test
	fun `exchange stores hashed refresh token and HttpOnly Cookie refreshes access token`() {
		val user = saveUser()
		val refreshCookie = exchangeForRefreshCookie(user)

		assertTrue(refreshCookie.isHttpOnly)
		assertFalse(refreshCookie.secure)
		assertEquals("Lax", refreshCookie.sameSite)
		assertEquals("/api/v1/auth", refreshCookie.path)
		assertEquals(Duration.ofDays(30).seconds.toInt(), refreshCookie.maxAge)

		val redisKey = "${RedisRefreshTokenStore.KEY_PREFIX}:${refreshTokenHasher.hash(refreshCookie.value)}"
		assertEquals(setOf(redisKey), redisTemplate.keys("${RedisRefreshTokenStore.KEY_PREFIX}:*"))
		assertFalse(redisKey.contains(refreshCookie.value))
		assertEquals(requireNotNull(user.id).toString(), redisTemplate.opsForValue().get(redisKey))
		assertTrue(redisTemplate.getExpire(redisKey) in 1..Duration.ofDays(30).seconds)

		val response = refresh(refreshCookie)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.tokenType", equalTo("Bearer"))
				jsonPath("$.data.accessToken") { isNotEmpty() }
				jsonPath("$.data.expiresAt") { isNotEmpty() }
			}
			.andReturn()
			.response
		val accessToken = objectMapper.readTree(response.contentAsByteArray)
			.at("/data/accessToken")
			.asText()
		assertEquals(user.id, jwtTokenService.parseUserId(accessToken))
	}

	@Test
	fun `missing expired revoked and deleted user refresh tokens return common 401`() {
		refresh(null)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}

		refresh(MockCookie("refresh_token", UNKNOWN_REFRESH_TOKEN))
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}

		val activeUser = saveUser()
		refreshTokenStore.save(
			EXPIRED_REFRESH_TOKEN,
			requireNotNull(activeUser.id),
			Duration.ofMillis(50),
		)
		Thread.sleep(150)
		refresh(MockCookie("refresh_token", EXPIRED_REFRESH_TOKEN))
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}

		val deletedUser = saveUser()
		val deletedUserCookie = exchangeForRefreshCookie(deletedUser)
		deletedUser.softDelete(TestFixtures.FIXED_INSTANT)
		userRepository.saveAndFlush(deletedUser)

		refresh(deletedUserCookie)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}
	}

	private fun exchangeForRefreshCookie(user: User): MockCookie {
		val code = exchangeCodeService.issue(requireNotNull(user.id))
		val setCookie = mockMvc.post("/api/v1/auth/token/exchange") {
			contentType = MediaType.APPLICATION_JSON
			content = objectMapper.writeValueAsString(mapOf("code" to code))
		}
			.andExpect {
				status { isOk() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
			.response
			.getHeader(HttpHeaders.SET_COOKIE)
		return MockCookie.parse(requireNotNull(setCookie))
	}

	private fun refresh(cookie: MockCookie?) = mockMvc.post("/api/v1/auth/token/refresh") {
		if (cookie != null) {
			cookie(cookie)
		}
	}

	private fun saveUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "refresh-${UUID.randomUUID()}",
			email = "refresh@example.com",
			name = "Refresh User",
		),
	)

	companion object {
		private val UNKNOWN_REFRESH_TOKEN = "u".repeat(43)
		private val EXPIRED_REFRESH_TOKEN = "e".repeat(43)
	}
}
