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
import org.springframework.test.web.servlet.MvcResult
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.time.Duration
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
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
	fun `exchange stores hashed family and refresh rotates token without extending absolute TTL`() {
		val user = saveUser()
		val originalCookie = exchangeForRefreshCookie(user)

		assertTrue(originalCookie.isHttpOnly)
		assertFalse(originalCookie.secure)
		assertEquals("Lax", originalCookie.sameSite)
		assertEquals(RefreshTokenCookieFactory.COOKIE_PATH, originalCookie.path)
		assertEquals(Duration.ofDays(30).seconds.toInt(), originalCookie.maxAge)

		val originalTokenKey = tokenKey(originalCookie.value)
		val familyKey = redisTemplate.keys("${RedisRefreshTokenStore.FAMILY_KEY_PREFIX}:*").single()
		assertEquals(setOf(originalTokenKey), redisTemplate.keys("${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:*"))
		assertTrue(redisTemplate.keys("${RedisRefreshTokenStore.USED_KEY_PREFIX}:*").isEmpty())
		assertFalse(originalTokenKey.contains(originalCookie.value))
		assertFalse(requireNotNull(redisTemplate.opsForValue().get(originalTokenKey)).contains(originalCookie.value))
		val ttlBeforeRotation = redisTemplate.getExpire(familyKey, TimeUnit.MILLISECONDS)

		Thread.sleep(25)
		val refreshResponse = refresh(originalCookie)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.tokenType", equalTo("Bearer"))
				jsonPath("$.data.accessToken") { isNotEmpty() }
				jsonPath("$.data.expiresAt") { isNotEmpty() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
		val rotatedCookie = refreshCookie(refreshResponse)
		assertNotEquals(originalCookie.value, rotatedCookie.value)
		assertTrue(rotatedCookie.isHttpOnly)

		val rotatedTokenKey = tokenKey(rotatedCookie.value)
		assertFalse(redisTemplate.hasKey(originalTokenKey))
		assertEquals(setOf(rotatedTokenKey), redisTemplate.keys("${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:*"))
		assertTrue(redisTemplate.hasKey(usedKey(originalCookie.value)))
		assertEquals(setOf(familyKey), redisTemplate.keys("${RedisRefreshTokenStore.FAMILY_KEY_PREFIX}:*"))
		val ttlAfterRotation = redisTemplate.getExpire(familyKey, TimeUnit.MILLISECONDS)
		assertTrue(ttlAfterRotation in 1..ttlBeforeRotation)

		val accessToken = objectMapper.readTree(refreshResponse.response.contentAsByteArray)
			.at("/data/accessToken")
			.asText()
		assertEquals(user.id, jwtTokenService.parseUserId(accessToken))
	}

	@Test
	fun `reusing rotated token revokes current family token`() {
		val originalCookie = exchangeForRefreshCookie(saveUser())
		val rotatedCookie = refreshCookie(
			refresh(originalCookie)
				.andExpect { status { isOk() } }
				.andReturn(),
		)

		val reusedResponse = refresh(originalCookie)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
		assertExpiredCookie(refreshCookie(reusedResponse))

		refresh(rotatedCookie)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}
		assertTrue(redisTemplate.keys("${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:*").isEmpty())
		assertTrue(redisTemplate.keys("${RedisRefreshTokenStore.FAMILY_KEY_PREFIX}:*").isEmpty())
	}

	@Test
	fun `missing expired unknown and deleted user refresh tokens return common 401 and expire cookie`() {
		assertInvalidRefresh(null)
		assertInvalidRefresh(MockCookie(RefreshTokenCookieFactory.COOKIE_NAME, UNKNOWN_REFRESH_TOKEN))

		val activeUser = saveUser()
		refreshTokenStore.save(
			EXPIRED_REFRESH_TOKEN,
			requireNotNull(activeUser.id),
			EXPIRED_FAMILY_ID,
			Duration.ofMillis(50),
		)
		Thread.sleep(150)
		assertInvalidRefresh(MockCookie(RefreshTokenCookieFactory.COOKIE_NAME, EXPIRED_REFRESH_TOKEN))

		val deletedUser = saveUser()
		val deletedUserCookie = exchangeForRefreshCookie(deletedUser)
		deletedUser.softDelete(TestFixtures.FIXED_INSTANT)
		userRepository.saveAndFlush(deletedUser)
		assertInvalidRefresh(deletedUserCookie)
		assertTrue(redisTemplate.keys("${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:*").isEmpty())
		assertTrue(redisTemplate.keys("${RedisRefreshTokenStore.FAMILY_KEY_PREFIX}:*").isEmpty())
	}

	private fun assertInvalidRefresh(cookie: MockCookie?) {
		val response = refresh(cookie)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
		assertExpiredCookie(refreshCookie(response))
	}

	private fun assertExpiredCookie(cookie: MockCookie) {
		assertEquals("", cookie.value)
		assertEquals(Duration.ZERO.seconds.toInt(), cookie.maxAge)
		assertEquals(RefreshTokenCookieFactory.COOKIE_PATH, cookie.path)
	}

	private fun exchangeForRefreshCookie(user: User): MockCookie {
		val code = exchangeCodeService.issue(requireNotNull(user.id))
		val response = mockMvc.post("/api/v1/auth/token/exchange") {
			contentType = MediaType.APPLICATION_JSON
			content = objectMapper.writeValueAsString(mapOf("code" to code))
		}
			.andExpect {
				status { isOk() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
		return refreshCookie(response)
	}

	private fun refresh(cookie: MockCookie?) = mockMvc.post("/api/v1/auth/token/refresh") {
		if (cookie != null) {
			cookie(cookie)
		}
	}

	private fun refreshCookie(result: MvcResult): MockCookie = MockCookie.parse(
		requireNotNull(result.response.getHeader(HttpHeaders.SET_COOKIE)),
	)

	private fun tokenKey(token: String): String =
		"${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:${refreshTokenHasher.hash(token)}"

	private fun usedKey(token: String): String =
		"${RedisRefreshTokenStore.USED_KEY_PREFIX}:${refreshTokenHasher.hash(token)}"

	private fun saveUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "refresh-${UUID.randomUUID()}",
			email = "refresh@example.com",
			name = "Refresh User",
		),
	)

	companion object {
		private const val EXPIRED_FAMILY_ID = "expired-family"
		private val UNKNOWN_REFRESH_TOKEN = "u".repeat(43)
		private val EXPIRED_REFRESH_TOKEN = "e".repeat(43)
	}
}
