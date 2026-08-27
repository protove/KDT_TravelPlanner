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
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class NaverOAuthFlowIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val objectMapper: ObjectMapper,
) {
	@Test
	fun `Naver OAuth creates user exchanges access token and updates user on relogin`() {
		profileName.set("First Naver Name")
		val firstExchangeCode = completeNaverLogin("first-login-code")

		exchange(firstExchangeCode)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.tokenType", equalTo("Bearer"))
				jsonPath("$.data.accessToken") { isNotEmpty() }
			}
		val createdUser = requireNotNull(
			userRepository.findByProviderAndProviderUserId(OAuthProvider.NAVER, NAVER_USER_ID),
		)
		assertEquals("First Naver Name", createdUser.name)
		assertEquals("naver@example.com", createdUser.email)

		profileName.set("Updated Naver Name")
		completeNaverLogin("second-login-code")

		val updatedUser = requireNotNull(
			userRepository.findByProviderAndProviderUserId(OAuthProvider.NAVER, NAVER_USER_ID),
		)
		assertEquals(createdUser.id, updatedUser.id)
		assertEquals("Updated Naver Name", updatedUser.name)
		assertEquals(1, userRepository.count())
	}

	@Test
	fun `Naver provider failure returns common 502 and consumed state cannot be reused`() {
		val (state, stateCookie) = startNaverLogin()

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
			param("code", "provider-error")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isBadGateway() }
				jsonPath("$.code", equalTo("OAUTH_PROVIDER_ERROR"))
				content { string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("provider-error"))) }
			}

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
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
	fun `Naver callback with mismatched browser state is rejected before provider call`() {
		val (state, stateCookie) = startNaverLogin()

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
			param("code", "provider-error")
			param("state", state)
			cookie(Cookie(OAuthStateCookieFactory.COOKIE_NAME, "different-state"))
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_OAUTH_STATE"))
			}

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
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
	fun `Naver access denied consumes state and redirects without provider call or user change`() {
		tokenRequestCount.set(0)
		val userCount = userRepository.count()
		val (state, stateCookie) = startNaverLogin()

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
			param("error", "access_denied")
			param("error_description", "User denied access")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isFound() }
				header { string(HttpHeaders.LOCATION, "$FRONTEND_REDIRECT_URL?error=access_denied") }
				header {
					string(
						HttpHeaders.SET_COOKIE,
						org.hamcrest.Matchers.containsString("${OAuthStateCookieFactory.COOKIE_NAME}=;"),
					)
				}
			}

		assertEquals(0, tokenRequestCount.get())
		assertEquals(userCount, userRepository.count())

		mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
			param("error", "access_denied")
			param("state", state)
			cookie(stateCookie)
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_OAUTH_STATE"))
			}
		assertEquals(0, tokenRequestCount.get())
	}

	private fun completeNaverLogin(authorizationCode: String): String {
		val (state, stateCookie) = startNaverLogin()
		val callbackResponse = mockMvc.get("/api/v1/auth/oauth2/naver/callback") {
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
		assertTrue(
			lastTokenRequestBody.get().contains("state=${URLEncoder.encode(state, StandardCharsets.UTF_8)}"),
		)
		return requireNotNull(
			UriComponentsBuilder.fromUriString(requireNotNull(callbackResponse.redirectedUrl))
				.build()
				.queryParams
				.getFirst("code"),
		)
	}

	@Test
	fun `start endpoint omits auth_type by default and forces reprompt only when switchAccount=true`() {
		val defaultLocation = mockMvc.get("/api/v1/auth/oauth2/naver")
			.andExpect { status { isFound() } }
			.andReturn()
			.response
			.redirectedUrl
		assertEquals(
			null,
			UriComponentsBuilder.fromUriString(requireNotNull(defaultLocation)).build().queryParams.getFirst("auth_type"),
		)

		val switchAccountLocation = mockMvc.get("/api/v1/auth/oauth2/naver") {
			param("switchAccount", "true")
		}
			.andExpect { status { isFound() } }
			.andReturn()
			.response
			.redirectedUrl
		assertEquals(
			"reprompt",
			UriComponentsBuilder.fromUriString(requireNotNull(switchAccountLocation)).build().queryParams.getFirst("auth_type"),
		)
	}

	private fun startNaverLogin(): Pair<String, Cookie> {
		val response = mockMvc.get("/api/v1/auth/oauth2/naver")
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
		private const val NAVER_USER_ID = "naver-integration-user"
		private const val FRONTEND_REDIRECT_URL = "http://localhost:3000/auth/callback"
		private const val AUTHORIZATION_URL = "http://nid.example/oauth2.0/authorize"
		private val profileName = AtomicReference("Naver User")
		private val lastTokenRequestBody = AtomicReference("")
		private val tokenRequestCount = AtomicInteger()
		private val naverServer: HttpServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
			.apply {
				createContext("/token", ::handleToken)
				createContext("/userinfo", ::handleUserInfo)
				start()
			}

		@JvmStatic
		@DynamicPropertySource
		fun naverProperties(registry: DynamicPropertyRegistry) {
			val baseUrl = "http://127.0.0.1:${naverServer.address.port}"
			registry.add("app.auth.oauth.naver.authorization-uri") { AUTHORIZATION_URL }
			registry.add("app.auth.oauth.naver.token-uri") { "$baseUrl/token" }
			registry.add("app.auth.oauth.naver.user-info-uri") { "$baseUrl/userinfo" }
		}

		@JvmStatic
		@AfterAll
		fun stopNaverServer() {
			naverServer.stop(0)
		}

		private fun handleToken(exchange: HttpExchange) {
			tokenRequestCount.incrementAndGet()
			val requestBody = exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8)
			lastTokenRequestBody.set(requestBody)
			if (requestBody.contains("code=provider-error")) {
				respond(exchange, 500, """{"error":"provider-internal-detail"}""")
				return
			}
			respond(exchange, 200, """{"access_token":"mock-naver-access"}""")
		}

		private fun handleUserInfo(exchange: HttpExchange) {
			if (exchange.requestHeaders.getFirst("Authorization") != "Bearer mock-naver-access") {
				respond(exchange, 401, """{"resultcode":"024","message":"invalid_token"}""")
				return
			}
			respond(
				exchange,
				200,
				"""{"resultcode":"00","message":"success","response":{"id":"$NAVER_USER_ID","email":"naver@example.com","name":"${profileName.get()}","profile_image":"https://images.example/naver.png"}}""",
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
