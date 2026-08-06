package com.ktcloud.travelplanner.auth.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.auth.repository.OneTimeTokenStore
import com.ktcloud.travelplanner.auth.service.OAuthExchangeCodeService
import com.ktcloud.travelplanner.global.security.JwtTokenService
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
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.time.Duration
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class AuthTokenControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val exchangeCodeService: OAuthExchangeCodeService,
	@Autowired private val tokenStore: OneTimeTokenStore,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@Test
	fun `exchanges Redis code for access token once`() {
		val user = saveUser()
		val code = exchangeCodeService.issue(requireNotNull(user.id))

		val firstResponse = exchange(code)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.tokenType", equalTo("Bearer"))
				jsonPath("$.data.accessToken") { isNotEmpty() }
				jsonPath("$.data.expiresAt") { isNotEmpty() }
			}
			.andReturn()
			.response
		val accessToken = objectMapper.readTree(firstResponse.contentAsByteArray)
			.at("/data/accessToken")
			.asText()
		assertEquals(user.id, jwtTokenService.parseUserId(accessToken))

		exchange(code)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_AUTHORIZATION_CODE"))
			}
	}

	@Test
	fun `expired and unknown codes return common 401 response`() {
		val user = saveUser()
		val expiredCode = "expired-${UUID.randomUUID()}"
		tokenStore.put(
			OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE,
			expiredCode,
			requireNotNull(user.id).toString(),
			Duration.ofMillis(50),
		)
		Thread.sleep(150)

		exchange(expiredCode)
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_AUTHORIZATION_CODE"))
			}
		exchange("unknown-code")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("INVALID_AUTHORIZATION_CODE"))
			}
	}

	@Test
	fun `blank code returns sorted validation error contract`() {
		exchange("")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("code"))
			}
	}

	private fun exchange(code: String) = mockMvc.post("/api/v1/auth/token/exchange") {
		contentType = MediaType.APPLICATION_JSON
		content = objectMapper.writeValueAsString(mapOf("code" to code))
	}

	private fun saveUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "exchange-${UUID.randomUUID()}",
			email = "exchange@example.com",
			name = "Exchange User",
		),
	)
}
