package com.ktcloud.travelplanner.auth.client

import com.ktcloud.travelplanner.auth.config.GoogleOAuthProperties
import com.ktcloud.travelplanner.auth.service.OAuthProviderException
import com.ktcloud.travelplanner.user.model.OAuthProvider
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
import java.net.URI
import kotlin.test.assertEquals

class GoogleOAuthClientTest {
	private lateinit var server: MockRestServiceServer
	private lateinit var client: GoogleOAuthClient

	@BeforeEach
	fun setUp() {
		val builder = RestClient.builder()
		server = MockRestServiceServer.bindTo(builder).build()
		client = GoogleOAuthClient(builder, properties())
	}

	@Test
	fun `creates Google authorization URL with required OIDC parameters`() {
		val authorizationUrl = client.createAuthorizationUrl("opaque-state")
		val parameters = UriComponentsBuilder.fromUri(authorizationUrl).build().queryParams

		assertEquals("test-client-id", parameters.getFirst("client_id"))
		assertEquals(CALLBACK_URL, parameters.getFirst("redirect_uri"))
		assertEquals("code", parameters.getFirst("response_type"))
		assertEquals("openid%20email%20profile", parameters.getFirst("scope"))
		assertEquals("opaque-state", parameters.getFirst("state"))
	}

	@Test
	fun `maps verified Google userinfo response to OAuth profile`() {
		server.expect(requestTo(TOKEN_URL))
			.andExpect(method(HttpMethod.POST))
			.andExpect(content().string(containsString("code=google-code")))
			.andRespond(withSuccess("""{"access_token":"google-access"}""", MediaType.APPLICATION_JSON))
		server.expect(requestTo(USER_INFO_URL))
			.andExpect(method(HttpMethod.GET))
			.andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer google-access"))
			.andRespond(
				withSuccess(
					"""{"sub":"google-user","email":"user@example.com","email_verified":true,"name":"Google User","picture":"https://images.example/profile.png"}""",
					MediaType.APPLICATION_JSON,
				),
			)

		val profile = client.fetchUserProfile("google-code")

		assertEquals(OAuthProvider.GOOGLE, profile.provider)
		assertEquals("google-user", profile.providerUserId)
		assertEquals("user@example.com", profile.email)
		assertEquals("Google User", profile.name)
		assertEquals("https://images.example/profile.png", profile.profileImageUrl)
		server.verify()
	}

	@Test
	fun `does not trust an unverified Google email`() {
		server.expect(requestTo(TOKEN_URL))
			.andRespond(withSuccess("""{"access_token":"google-access"}""", MediaType.APPLICATION_JSON))
		server.expect(requestTo(USER_INFO_URL))
			.andRespond(
				withSuccess(
					"""{"sub":"google-user","email":"unverified@example.com","email_verified":false}""",
					MediaType.APPLICATION_JSON,
				),
			)

		assertEquals(null, client.fetchUserProfile("google-code").email)
	}

	@Test
	fun `maps Google HTTP failure without exposing provider response`() {
		server.expect(requestTo(TOKEN_URL)).andRespond(withServerError())

		val exception = assertThrows<OAuthProviderException> {
			client.fetchUserProfile("sensitive-google-code")
		}

		assertEquals("OAuth 제공자 통신에 실패했습니다.", exception.message)
	}

	@Test
	fun `rejects use when Google credentials are not configured`() {
		val unconfiguredClient = GoogleOAuthClient(
			RestClient.builder(),
			properties(clientId = "", clientSecret = ""),
		)

		assertThrows<OAuthProviderException> {
			unconfiguredClient.createAuthorizationUrl("state")
		}
	}

	private fun properties(
		clientId: String = "test-client-id",
		clientSecret: String = "test-client-secret",
	): GoogleOAuthProperties = GoogleOAuthProperties(
		clientId = clientId,
		clientSecret = clientSecret,
		redirectUri = URI.create(CALLBACK_URL),
		authorizationUri = URI.create(AUTHORIZATION_URL),
		tokenUri = URI.create(TOKEN_URL),
		userInfoUri = URI.create(USER_INFO_URL),
	)

	companion object {
		private const val AUTHORIZATION_URL = "https://accounts.example/oauth2/auth"
		private const val TOKEN_URL = "https://oauth.example/token"
		private const val USER_INFO_URL = "https://openid.example/userinfo"
		private const val CALLBACK_URL = "http://localhost:8080/api/v1/auth/oauth2/google/callback"
	}
}
