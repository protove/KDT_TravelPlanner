package com.ktcloud.travelplanner.auth.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.repository.UserRepository
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import jakarta.servlet.http.Cookie
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import org.springframework.web.util.UriComponentsBuilder
import java.net.InetSocketAddress
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class GoogleOAuthFlowIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@Test
	fun `Google OAuth creates user exchanges access token and updates user on relogin`() {
		profileName.set("First Google Name")
		val firstExchangeCode = completeGoogleLogin("first-login-code")

		exchange(firstExchangeCode)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.tokenType", equalTo("Bearer"))
				jsonPath("$.data.accessToken") { isNotEmpty() }
			}
		val createdUser = requireNotNull(
			userRepository.findByProviderAndProviderUserId(OAuthProvider.GOOGLE, GOOGLE_USER_ID),
		)
		assertEquals("First Google Name", createdUser.name)
		assertEquals("google@example.com", createdUser.email)

		profileName.set("Updated Google Name")
		completeGoogleLogin("second-login-code")

		val updatedUser = requireNotNull(
			userRepository.findByProviderAndProviderUserId(OAuthProvider.GOOGLE, GOOGLE_USER_ID),
		)
		assertEquals(createdUser.id, updatedUser.id)
		assertEquals("Updated Google Name", updatedUser.name)
		assertEquals(1, userRepository.count())
	}

	@Test
	fun `Google provider failure returns common 502 and consumed state cannot be reused`() {
		val (state, stateCookie) = startGoogleLogin()

		mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", "provider-error")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isBadGateway() }
				jsonPath("$.code", equalTo("OAUTH_PROVIDER_ERROR"))
				content { string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("provider-error"))) }
			}

		mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", "provider-error")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_OAUTH_STATE"))
			}
	}

	@Test
	fun `Google callback without browser state is rejected before provider call and state remains usable`() {
		val (state, stateCookie) = startGoogleLogin()

		mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", "provider-error")
			param("state", state)
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_OAUTH_STATE"))
			}

		mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", "provider-error")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isBadGateway() }
				jsonPath("$.code", equalTo("OAUTH_PROVIDER_ERROR"))
			}
	}

	@Test
	fun `blank Google callback parameters return common 400 response`() {
		mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", "")
			param("state", "")
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
	}

	private fun completeGoogleLogin(authorizationCode: String): String {
		val (state, stateCookie) = startGoogleLogin()
		val callbackResponse = mockMvc.get("/api/v1/auth/oauth2/google/callback") {
			param("code", authorizationCode)
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isFound() }
				header { string("Location", org.hamcrest.Matchers.startsWith(FRONTEND_REDIRECT_URL)) }
				header {
					string(
						HttpHeaders.SET_COOKIE,
						org.hamcrest.Matchers.containsString("${OAuthStateCookieFactory.COOKIE_NAME}=;"),
					)
				}
			}
			.andReturn()
			.response
		return requireNotNull(
			UriComponentsBuilder.fromUriString(requireNotNull(callbackResponse.redirectedUrl))
				.build()
				.queryParams
				.getFirst("code"),
		)
	}

	private fun startGoogleLogin(): Pair<String, Cookie> {
		val response = mockMvc.get("/api/v1/auth/oauth2/google")
			.andExpect {
				status { isFound() }
				header { string("Location", org.hamcrest.Matchers.startsWith(AUTHORIZATION_URL)) }
			}
			.andReturn()
			.response
		val state = requireNotNull(
			UriComponentsBuilder.fromUriString(requireNotNull(response.redirectedUrl))
				.build()
				.queryParams
				.getFirst("state"),
		)
		return state to requireNotNull(response.getCookie(OAuthStateCookieFactory.COOKIE_NAME))
	}

	private fun exchange(code: String) = mockMvc.post("/api/v1/auth/token/exchange") {
		contentType = MediaType.APPLICATION_JSON
		content = objectMapper.writeValueAsString(mapOf("code" to code))
	}

	companion object {
		private const val GOOGLE_USER_ID = "google-integration-user"
		private const val FRONTEND_REDIRECT_URL = "http://localhost:3000/auth/callback"
		private const val AUTHORIZATION_URL = "http://accounts.example/oauth2/auth"
		private val profileName = AtomicReference("Google User")
		private val googleServer: HttpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
			.apply {
				createContext("/token", ::handleToken)
				createContext("/userinfo", ::handleUserInfo)
				start()
			}

		@JvmStatic
		@DynamicPropertySource
		fun googleProperties(registry: DynamicPropertyRegistry) {
			val baseUrl = "http://127.0.0.1:${googleServer.address.port}"
			registry.add("app.auth.oauth.google.authorization-uri") { AUTHORIZATION_URL }
			registry.add("app.auth.oauth.google.token-uri") { "$baseUrl/token" }
			registry.add("app.auth.oauth.google.user-info-uri") { "$baseUrl/userinfo" }
		}

		@JvmStatic
		@AfterAll
		fun stopGoogleServer() {
			googleServer.stop(0)
		}

		private fun handleToken(exchange: HttpExchange) {
			val requestBody = exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8)
			if (requestBody.contains("code=provider-error")) {
				respond(exchange, 500, """{"error":"provider-internal-detail"}""")
				return
			}
			respond(exchange, 200, """{"access_token":"mock-google-access"}""")
		}

		private fun handleUserInfo(exchange: HttpExchange) {
			if (exchange.requestHeaders.getFirst("Authorization") != "Bearer mock-google-access") {
				respond(exchange, 401, """{"error":"invalid_token"}""")
				return
			}
			respond(
				exchange,
				200,
				"""{"sub":"$GOOGLE_USER_ID","email":"google@example.com","email_verified":true,"name":"${profileName.get()}","picture":"https://images.example/google.png"}""",
			)
		}

		private fun respond(exchange: HttpExchange, status: Int, body: String) {
			val bytes = body.toByteArray(StandardCharsets.UTF_8)
			exchange.responseHeaders.set("Content-Type", MediaType.APPLICATION_JSON_VALUE)
			exchange.sendResponseHeaders(status, bytes.size.toLong())
			exchange.responseBody.use { it.write(bytes) }
		}
	}
}
