package com.ktcloud.travelplanner.user.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.auth.controller.RefreshTokenCookieFactory
import com.ktcloud.travelplanner.auth.repository.RedisRefreshTokenStore
import com.ktcloud.travelplanner.auth.repository.RefreshTokenHasher
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
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.mock.web.MockCookie
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.delete
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.time.Duration
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class UserAccountDeletionIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val exchangeCodeService: OAuthExchangeCodeService,
	@Autowired private val objectMapper: ObjectMapper,
	@Autowired private val redisTemplate: StringRedisTemplate,
	@Autowired private val refreshTokenHasher: RefreshTokenHasher,
	@Autowired private val jdbcTemplate: JdbcTemplate,
) {
	@Test
	fun `account deletion soft deletes user revokes refresh token and blocks existing tokens`() {
		val authentication = login()
		val refreshTokenKey = "${RedisRefreshTokenStore.TOKEN_KEY_PREFIX}:${refreshTokenHasher.hash(authentication.refreshCookie.value)}"
		assertTrue(redisTemplate.hasKey(refreshTokenKey))

		val deleteResponse = mockMvc.delete("/api/v1/users/me") {
			header(HttpHeaders.AUTHORIZATION, "Bearer ${authentication.accessToken}")
			cookie(authentication.refreshCookie)
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data") { exists() }
				header { exists(HttpHeaders.SET_COOKIE) }
			}
			.andReturn()
			.response

		val expiredCookie = MockCookie.parse(assertNotNull(deleteResponse.getHeader(HttpHeaders.SET_COOKIE)))
		assertEquals("", expiredCookie.value)
		assertEquals(Duration.ZERO.seconds.toInt(), expiredCookie.maxAge)
		assertEquals(RefreshTokenCookieFactory.COOKIE_PATH, expiredCookie.path)
		assertFalse(redisTemplate.hasKey(refreshTokenKey))
		assertTrue(
			jdbcTemplate.queryForObject(
				"SELECT deleted_at IS NOT NULL FROM user_table WHERE id = ?",
				Boolean::class.java,
				authentication.userId,
			) == true,
		)

		mockMvc.get("/api/v1/users/me/profile") {
			header(HttpHeaders.AUTHORIZATION, "Bearer ${authentication.accessToken}")
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}

		mockMvc.post("/api/v1/auth/token/refresh") {
			cookie(authentication.refreshCookie)
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_REFRESH_TOKEN"))
			}

		mockMvc.delete("/api/v1/users/me") {
			header(HttpHeaders.AUTHORIZATION, "Bearer ${authentication.accessToken}")
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `account deletion requires authentication`() {
		mockMvc.delete("/api/v1/users/me")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun login(): AuthenticationFixture {
		val user = userRepository.saveAndFlush(
			User(
				provider = OAuthProvider.GOOGLE,
				providerUserId = "delete-account-${UUID.randomUUID()}",
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

		return AuthenticationFixture(
			userId = requireNotNull(user.id),
			accessToken = objectMapper.readTree(response.contentAsByteArray).at("/data/accessToken").asText(),
			refreshCookie = MockCookie.parse(assertNotNull(response.getHeader(HttpHeaders.SET_COOKIE))),
		)
	}

	private data class AuthenticationFixture(
		val userId: UUID,
		val accessToken: String,
		val refreshCookie: MockCookie,
	)
}
