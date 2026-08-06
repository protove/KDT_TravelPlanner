package com.ktcloud.travelplanner.auth.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties("app.auth.oauth.http-client")
data class OAuthHttpClientProperties(
	val connectTimeout: Duration = Duration.ofSeconds(3),
	val readTimeout: Duration = Duration.ofSeconds(5),
) {
	init {
		require(!connectTimeout.isZero && !connectTimeout.isNegative) {
			"OAuth HTTP connect timeout must be positive."
		}
		require(!readTimeout.isZero && !readTimeout.isNegative) {
			"OAuth HTTP read timeout must be positive."
		}
	}
}
