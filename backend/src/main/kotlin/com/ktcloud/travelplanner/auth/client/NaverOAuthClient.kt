package com.ktcloud.travelplanner.auth.client

import com.fasterxml.jackson.annotation.JsonProperty
import com.ktcloud.travelplanner.auth.config.NaverOAuthProperties
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

private data class NaverTokenResponse(
	@JsonProperty("access_token")
	val accessToken: String,
)

private data class NaverUserInfoResponse(
	@JsonProperty("resultcode")
	val resultCode: String,
	val response: NaverUserProfileResponse? = null,
)

private data class NaverUserProfileResponse(
	val id: String,
	val email: String? = null,
	val name: String? = null,
	@JsonProperty("profile_image")
	val profileImageUrl: String? = null,
)

@Component
class NaverOAuthClient(
	restClientBuilder: RestClient.Builder,
	private val properties: NaverOAuthProperties,
) : OAuthProviderClient {
	private val restClient = restClientBuilder.build()

	override val provider: OAuthProvider = OAuthProvider.NAVER

	override fun createAuthorizationUrl(state: String): URI {
		properties.requireConfigured()
		return UriComponentsBuilder.fromUri(properties.authorizationUri)
			.queryParam("client_id", properties.clientId)
			.queryParam("redirect_uri", properties.redirectUri)
			.queryParam("response_type", "code")
			.queryParam("state", state)
			.build()
			.encode()
			.toUri()
	}

	override fun fetchUserProfile(grant: OAuthAuthorizationGrant): OAuthUserProfile {
		properties.requireConfigured()
		return try {
			val tokenResponse = exchangeAuthorizationCode(grant)
			val userInfo = fetchUserInfo(tokenResponse.accessToken)
			val profile = userInfo.response
			if (userInfo.resultCode != SUCCESS_RESULT_CODE || profile == null || profile.id.isBlank()) {
				throw OAuthProviderException()
			}
			OAuthUserProfile(
				provider = provider,
				providerUserId = profile.id,
				email = profile.email,
				name = profile.name,
				profileImageUrl = profile.profileImageUrl,
			)
		} catch (exception: OAuthProviderException) {
			throw exception
		} catch (exception: RestClientException) {
			throw OAuthProviderException(exception)
		}
	}

	private fun exchangeAuthorizationCode(grant: OAuthAuthorizationGrant): NaverTokenResponse {
		val form = LinkedMultiValueMap<String, String>().apply {
			add("client_id", properties.clientId)
			add("client_secret", properties.clientSecret)
			add("code", grant.authorizationCode)
			add("grant_type", "authorization_code")
			add("state", grant.state)
		}
		return restClient.post()
			.uri(properties.tokenUri)
			.contentType(MediaType.APPLICATION_FORM_URLENCODED)
			.body(form)
			.retrieve()
			.body(NaverTokenResponse::class.java)
			?.takeIf { it.accessToken.isNotBlank() }
			?: throw OAuthProviderException()
	}

	private fun fetchUserInfo(accessToken: String): NaverUserInfoResponse =
		restClient.get()
			.uri(properties.userInfoUri)
			.header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			.retrieve()
			.body(NaverUserInfoResponse::class.java)
			?: throw OAuthProviderException()

	companion object {
		private const val SUCCESS_RESULT_CODE = "00"
	}
}
