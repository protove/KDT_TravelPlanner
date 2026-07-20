package com.ktcloud.travelplanner.global.security

import org.springframework.boot.context.properties.ConfigurationProperties
import java.nio.charset.StandardCharsets
import java.time.Duration

@ConfigurationProperties("app.security.jwt")
data class JwtProperties(
	val issuer: String,
	val accessTokenTtl: Duration,
	val secret: String,
) {
	init {
		require(issuer.isNotBlank()) { "JWT issuer must not be blank." }
		require(!accessTokenTtl.isZero && !accessTokenTtl.isNegative) {
			"JWT access token TTL must be positive."
		}
		require(secret.toByteArray(StandardCharsets.UTF_8).size >= MIN_SECRET_BYTES) {
			"JWT secret must contain at least $MIN_SECRET_BYTES bytes."
		}
	}

	companion object {
		const val MIN_SECRET_BYTES = 32
	}
}
