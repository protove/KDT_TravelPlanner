package com.ktcloud.travelplanner.auth.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties("app.auth.refresh-token")
data class RefreshTokenProperties(
	val ttl: Duration,
	val cookieSecure: Boolean,
	val cookieSameSite: String,
) {
	init {
		require(!ttl.isZero && !ttl.isNegative) { "Refresh Token TTL must be positive." }
		require(cookieSameSite in ALLOWED_SAME_SITE_VALUES) {
			"Refresh Token Cookie SameSite must be Strict, Lax, or None."
		}
		require(cookieSameSite != "None" || cookieSecure) {
			"Refresh Token Cookie with SameSite=None must be Secure."
		}
	}

	companion object {
		private val ALLOWED_SAME_SITE_VALUES = setOf("Strict", "Lax", "None")
	}
}
