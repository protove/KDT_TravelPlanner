package com.ktcloud.travelplanner.auth.client

import com.ktcloud.travelplanner.auth.config.NaverOAuthProperties
import com.ktcloud.travelplanner.auth.config.OAuthHttpClientConfiguration
import com.ktcloud.travelplanner.auth.config.OAuthHttpClientProperties
import com.ktcloud.travelplanner.auth.service.OAuthProviderException
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.sun.net.httpserver.HttpServer
import org.hamcrest.Matchers.allOf
import org.hamcrest.Matchers.containsString
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpMethod
import org.springframework.http.MediaType
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.content
import org.springframework.test.web.client.match.MockRestRequestMatchers.header
import org.springframework.test.web.client.match.MockRestRequestMatchers.method
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withServerError
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.web.client.RestClient
import org.springframework.web.util.UriComponentsBuilder
import java.net.InetSocketAddress
import java.net.URI
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class NaverOAuthClientTest {
	private lateinit var server: MockRestServiceServer
	private lateinit var client: NaverOAuthClient

	@BeforeEach
	fun setUp() {
		val builder = RestClient.builder()
		server = MockRestServiceServer.bindTo(builder).build()
		client = NaverOAuthClient(builder.build(), properties())
	}

	@Test
	fun `creates Naver authorization URL with required parameters`() {
		val authorizationUrl = client.createAuthorizationUrl("opaque-state")
		val parameters = UriComponentsBuilder.fromUri(authorizationUrl).build().queryParams

		assertEquals("test-client-id", parameters.getFirst("client_id"))
		assertEquals(CALLBACK_URL, parameters.getFirst("redirect_uri"))
		assertEquals("code", parameters.getFirst("response_type"))
		assertEquals("opaque-state", parameters.getFirst("state"))
		assertEquals("reprompt", parameters.getFirst("auth_type"))
	}

	@Test
	fun `maps nested Naver profile and sends verified state to token endpoint`() {
		server.expect(requestTo(TOKEN_URL))
			.andExpect(method(HttpMethod.POST))
			.andExpect(
				content().string(
					allOf(
						containsString("code=naver-code"),
						containsString("state=verified-state"),
					),
				),
			)
			.andRespond(withSuccess("""{"access_token":"naver-access"}""", MediaType.APPLICATION_JSON))
		server.expect(requestTo(USER_INFO_URL))
			.andExpect(method(HttpMethod.GET))
			.andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer naver-access"))
			.andRespond(
				withSuccess(
					"""{"resultcode":"00","message":"success","response":{"id":"naver-user","email":"naver@example.com","name":"Naver User","profile_image":"https://images.example/naver.png"}}""",
					MediaType.APPLICATION_JSON,
				),
			)

		val profile = client.fetchUserProfile(grant())

		assertEquals(OAuthProvider.NAVER, profile.provider)
		assertEquals("naver-user", profile.providerUserId)
		assertEquals("naver@example.com", profile.email)
		assertEquals("Naver User", profile.name)
		assertEquals("https://images.example/naver.png", profile.profileImageUrl)
		server.verify()
	}

	@Test
	fun `maps unsuccessful Naver result to provider error`() {
		server.expect(requestTo(TOKEN_URL))
			.andRespond(withSuccess("""{"access_token":"naver-access"}""", MediaType.APPLICATION_JSON))
		server.expect(requestTo(USER_INFO_URL))
			.andRespond(
				withSuccess(
					"""{"resultcode":"024","message":"authentication failed"}""",
					MediaType.APPLICATION_JSON,
				),
			)

		assertThrows<OAuthProviderException> {
			client.fetchUserProfile(grant())
		}
	}

	@Test
	fun `maps Naver HTTP failure without exposing provider response`() {
		server.expect(requestTo(TOKEN_URL)).andRespond(withServerError())

		val exception = assertThrows<OAuthProviderException> {
			client.fetchUserProfile(grant("sensitive-naver-code"))
		}

		assertEquals("OAuth 제공자 통신에 실패했습니다.", exception.message)
	}

	@Test
	fun `times out a delayed Naver token response without exposing credentials`() {
		val delayedServer = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
			createContext("/token") { exchange ->
				Thread.sleep(300)
				exchange.close()
			}
			start()
		}
		try {
			val timeoutClient = NaverOAuthClient(
				OAuthHttpClientConfiguration().oauthRestClient(
					RestClient.builder(),
					OAuthHttpClientProperties(
						connectTimeout = Duration.ofSeconds(1),
						readTimeout = Duration.ofMillis(50),
					),
				),
				properties(tokenUri = "http://127.0.0.1:${delayedServer.address.port}/token"),
			)

			val exception = assertThrows<OAuthProviderException> {
				timeoutClient.fetchUserProfile(grant("sensitive-naver-code"))
			}

			assertEquals("OAuth 제공자 통신에 실패했습니다.", exception.message)
			assertFalse(exception.message.orEmpty().contains("sensitive-naver-code"))
			assertFalse(exception.message.orEmpty().contains("test-client-secret"))
		} finally {
			delayedServer.stop(0)
		}
	}

	@Test
	fun `rejects use when Naver credentials are not configured`() {
		val unconfiguredClient = NaverOAuthClient(
			RestClient.builder().build(),
			properties(clientId = "", clientSecret = ""),
		)

		assertThrows<OAuthProviderException> {
			unconfiguredClient.createAuthorizationUrl("state")
		}
	}

	private fun grant(authorizationCode: String = "naver-code") = OAuthAuthorizationGrant(
		authorizationCode = authorizationCode,
		state = "verified-state",
	)

	private fun properties(
		clientId: String = "test-client-id",
		clientSecret: String = "test-client-secret",
		tokenUri: String = TOKEN_URL,
	): NaverOAuthProperties = NaverOAuthProperties(
		clientId = clientId,
		clientSecret = clientSecret,
		redirectUri = URI.create(CALLBACK_URL),
		authorizationUri = URI.create(AUTHORIZATION_URL),
		tokenUri = URI.create(tokenUri),
		userInfoUri = URI.create(USER_INFO_URL),
	)

	companion object {
		private const val AUTHORIZATION_URL = "https://nid.example/oauth2.0/authorize"
		private const val TOKEN_URL = "https://nid.example/oauth2.0/token"
		private const val USER_INFO_URL = "https://openapi.example/v1/nid/me"
		private const val CALLBACK_URL = "http://localhost:8080/api/v1/auth/oauth2/naver/callback"
	}
}
