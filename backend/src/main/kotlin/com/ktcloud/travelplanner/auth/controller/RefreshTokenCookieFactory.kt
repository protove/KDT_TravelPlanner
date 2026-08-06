package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import org.springframework.http.ResponseCookie
import org.springframework.stereotype.Component
import java.time.Duration

@Component
class RefreshTokenCookieFactory(
	private val properties: RefreshTokenProperties,
) {
	fun create(value: String): ResponseCookie = builder(value)
		.maxAge(properties.ttl)
		.build()

	fun expire(): ResponseCookie = builder("")
		.maxAge(Duration.ZERO)
		.build()

	private fun builder(value: String): ResponseCookie.ResponseCookieBuilder =
		ResponseCookie.from(COOKIE_NAME, value)
			.httpOnly(true)
			.secure(properties.cookieSecure)
			.sameSite(properties.cookieSameSite)
			.path(COOKIE_PATH)

	companion object {
		const val COOKIE_NAME = "refresh_token"
		const val COOKIE_PATH = "/api/v1/auth"
	}
}
