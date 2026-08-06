package com.ktcloud.travelplanner.auth.config

import com.ktcloud.travelplanner.auth.service.OAuthProviderException
import org.springframework.boot.context.properties.ConfigurationProperties
import java.net.URI

@ConfigurationProperties("app.auth.oauth.google")
data class GoogleOAuthProperties(
	val clientId: String,
	val clientSecret: String,
	val redirectUri: URI,
	val authorizationUri: URI,
	val tokenUri: URI,
	val userInfoUri: URI,
) {
	fun requireConfigured() {
		if (clientId.isBlank() || clientSecret.isBlank()) {
			throw OAuthProviderException()
		}
	}
}
