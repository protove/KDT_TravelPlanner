package com.ktcloud.travelplanner.auth.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.net.URI
import java.time.Duration

@ConfigurationProperties("app.auth.oauth")
data class OAuthFlowProperties(
	val stateTtl: Duration,
	val exchangeCodeTtl: Duration,
	val allowedRedirectOrigins: List<String>,
	val frontendRedirectUrl: String,
) {
	val parsedAllowedRedirectOrigins: Set<URI> = allowedRedirectOrigins
		.map(::parseOrigin)
		.toSet()

	init {
		require(!stateTtl.isZero && !stateTtl.isNegative) { "OAuth state TTL must be positive." }
		require(!exchangeCodeTtl.isZero && !exchangeCodeTtl.isNegative) {
			"OAuth exchange code TTL must be positive."
		}
		require(allowedRedirectOrigins.isNotEmpty()) {
			"At least one OAuth redirect origin must be configured."
		}
		require(frontendRedirectUrl.isNotBlank()) {
			"OAuth frontend redirect URL must not be blank."
		}
	}

	private fun parseOrigin(value: String): URI {
		val origin = URI.create(value.trim())
		require(origin.scheme == "http" || origin.scheme == "https") {
			"OAuth redirect origin must use HTTP or HTTPS."
		}
		require(origin.host != null && origin.userInfo == null) {
			"OAuth redirect origin must contain a valid host without user info."
		}
		require(origin.path.isNullOrEmpty() && origin.query == null && origin.fragment == null) {
			"OAuth redirect origin must not contain a path, query, or fragment."
		}
		return normalizeOrigin(origin)
	}

	companion object {
		fun normalizeOrigin(uri: URI): URI = URI(
			uri.scheme.lowercase(),
			null,
			uri.host.lowercase(),
			normalizePort(uri),
			null,
			null,
			null,
		)

		private fun normalizePort(uri: URI): Int = when {
			uri.port >= 0 -> uri.port
			uri.scheme.equals("http", ignoreCase = true) -> 80
			else -> 443
		}
	}
}
