package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import org.springframework.http.ResponseCookie
import org.springframework.stereotype.Component
import java.time.Duration

@Component
class OAuthStateCookieFactory(
	private val properties: OAuthFlowProperties,
) {
	fun create(state: String): ResponseCookie = builder(state)
		.maxAge(properties.stateTtl)
		.build()

	fun expire(): ResponseCookie = builder("")
		.maxAge(Duration.ZERO)
		.build()

	private fun builder(value: String): ResponseCookie.ResponseCookieBuilder =
		ResponseCookie.from(COOKIE_NAME, value)
			.httpOnly(true)
			.secure(properties.stateCookieSecure)
			.sameSite(COOKIE_SAME_SITE)
			.path(COOKIE_PATH)

	companion object {
		const val COOKIE_NAME = "oauth_state"
		const val COOKIE_PATH = "/api/v1/auth/oauth2"
		const val COOKIE_SAME_SITE = "Lax"
	}
}
