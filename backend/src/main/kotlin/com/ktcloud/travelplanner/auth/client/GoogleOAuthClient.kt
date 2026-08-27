package com.ktcloud.travelplanner.auth.client

import com.fasterxml.jackson.annotation.JsonProperty
import com.ktcloud.travelplanner.auth.config.GoogleOAuthProperties
import com.ktcloud.travelplanner.auth.service.OAuthProviderException
import com.ktcloud.travelplanner.user.model.OAuthProvider
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.util.LinkedMultiValueMap
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import org.springframework.web.util.UriComponentsBuilder
import java.net.URI

private data class GoogleTokenResponse(
	@JsonProperty("access_token")
	val accessToken: String,
)

private data class GoogleUserInfoResponse(
	val sub: String,
	val email: String? = null,
	@JsonProperty("email_verified")
	val isEmailVerified: Boolean? = null,
	val name: String? = null,
	val picture: String? = null,
)

@Component
class GoogleOAuthClient(
	private val restClient: RestClient,
	private val properties: GoogleOAuthProperties,
) : OAuthProviderClient {
	override val provider: OAuthProvider = OAuthProvider.GOOGLE

	override fun createAuthorizationUrl(
		state: String,
		forceAccountSelection: Boolean,
	): URI {
		properties.requireConfigured()
		val builder = UriComponentsBuilder.fromUri(properties.authorizationUri)
			.queryParam("client_id", properties.clientId)
			.queryParam("redirect_uri", properties.redirectUri)
			.queryParam("response_type", "code")
			.queryParam("scope", SCOPES.joinToString(" "))
			.queryParam("state", state)
		if (forceAccountSelection) {
			builder.queryParam("prompt", "select_account")
		}
		return builder.build().encode().toUri()
	}

	override fun fetchUserProfile(grant: OAuthAuthorizationGrant): OAuthUserProfile {
		properties.requireConfigured()
		return try {
			val tokenResponse = exchangeAuthorizationCode(grant.authorizationCode)
			val userInfo = fetchUserInfo(tokenResponse.accessToken)
			if (userInfo.sub.isBlank()) {
				throw OAuthProviderException()
			}
			OAuthUserProfile(
				provider = provider,
				providerUserId = userInfo.sub,
				email = userInfo.email.takeIf { userInfo.isEmailVerified == true },
				name = userInfo.name,
				profileImageUrl = userInfo.picture,
			)
		} catch (exception: OAuthProviderException) {
			throw exception
		} catch (exception: RestClientException) {
			throw OAuthProviderException(exception)
		}
	}

	private fun exchangeAuthorizationCode(authorizationCode: String): GoogleTokenResponse {
		val form = LinkedMultiValueMap<String, String>().apply {
			add("client_id", properties.clientId)
			add("client_secret", properties.clientSecret)
			add("code", authorizationCode)
			add("grant_type", "authorization_code")
			add("redirect_uri", properties.redirectUri.toASCIIString())
		}
		return restClient.post()
			.uri(properties.tokenUri)
			.contentType(MediaType.APPLICATION_FORM_URLENCODED)
			.body(form)
			.retrieve()
			.body(GoogleTokenResponse::class.java)
			?.takeIf { it.accessToken.isNotBlank() }
			?: throw OAuthProviderException()
	}

	private fun fetchUserInfo(accessToken: String): GoogleUserInfoResponse =
		restClient.get()
			.uri(properties.userInfoUri)
			.header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			.retrieve()
			.body(GoogleUserInfoResponse::class.java)
			?: throw OAuthProviderException()

	companion object {
		private val SCOPES = listOf("openid", "email", "profile")
	}
}
