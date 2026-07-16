package com.ktcloud.travelplanner.place.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
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
import org.springframework.transaction.annotation.Transactional
import java.net.InetSocketAddress
import java.nio.charset.StandardCharsets
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class PlaceSearchControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
) {
	@Test
	fun `authenticated user searches places through Google adapter`() {
		val user = saveUser("place-search-user")

		mockMvc.get("/api/v1/places/search") {
			header(HttpHeaders.AUTHORIZATION, bearer(user))
			param("query", "도쿄 타워")
			param("countryCode", "jp")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data[0].placeId", equalTo("place-success"))
			jsonPath("$.data[0].name", equalTo("도쿄 타워"))
			jsonPath("$.data[0].rating", equalTo(4.5))
		}
	}

	@Test
	fun `invalid input and Google failures use common error responses`() {
		val user = saveUser("place-error-user")
		listOf(
			Triple("", "KR", 400),
			Triple("정상", "K1", 400),
			Triple("quota", "KR", 503),
			Triple("client-error", "KR", 502),
			Triple("provider-error", "KR", 502),
			Triple("timeout", "KR", 504),
		).forEach { (query, countryCode, expectedStatus) ->
			mockMvc.get("/api/v1/places/search") {
				header(HttpHeaders.AUTHORIZATION, bearer(user))
				param("query", query)
				param("countryCode", countryCode)
			}.andExpect { status { isEqualTo(expectedStatus) } }
		}
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "place-search-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	companion object {
		private val googleServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
			createContext("/v1/places:searchText", ::handleSearch)
			start()
		}

		@JvmStatic
		@DynamicPropertySource
		fun googlePlacesProperties(registry: DynamicPropertyRegistry) {
			registry.add("app.external.google.places.api-key") { "integration-places-key" }
			registry.add("app.external.google.places.base-url") {
				"http://127.0.0.1:${googleServer.address.port}"
			}
			registry.add("app.external.google.places.read-timeout") { "100ms" }
		}

		@JvmStatic
		@AfterAll
		fun stopGoogleServer() {
			googleServer.stop(0)
		}

		private fun handleSearch(exchange: HttpExchange) {
			val body = exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8)
			when {
				body.contains("timeout") -> {
					Thread.sleep(250)
					respond(exchange, 200, "{}")
				}
				body.contains("quota") -> respond(exchange, 429, """{"error":"quota-detail"}""")
				body.contains("client-error") -> respond(exchange, 400, """{"error":"client-detail"}""")
				body.contains("provider-error") -> respond(exchange, 500, """{"error":"provider-detail"}""")
				else -> respond(
					exchange,
					200,
					"""{"places":[{"id":"place-success","displayName":{"text":"도쿄 타워"},"location":{"latitude":35.658581,"longitude":139.745433},"rating":4.5}]}""",
				)
			}
		}

		private fun respond(exchange: HttpExchange, status: Int, body: String) {
			val bytes = body.toByteArray(StandardCharsets.UTF_8)
			exchange.responseHeaders.set("Content-Type", MediaType.APPLICATION_JSON_VALUE)
			exchange.sendResponseHeaders(status, bytes.size.toLong())
			exchange.responseBody.use { it.write(bytes) }
		}
	}
}
