package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.service.RefreshTokenService
import com.ktcloud.travelplanner.global.response.ApiResponse
import jakarta.servlet.http.HttpServletResponse
import org.springframework.http.HttpHeaders
import org.springframework.web.bind.annotation.CookieValue
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/auth")
class LogoutController(
	private val refreshTokenService: RefreshTokenService,
	private val refreshTokenCookieFactory: RefreshTokenCookieFactory,
) {
	@PostMapping("/logout")
	fun logout(
		@CookieValue(name = RefreshTokenCookieFactory.COOKIE_NAME, required = false) refreshToken: String?,
		response: HttpServletResponse,
	): ApiResponse<Unit> {
		refreshTokenService.revoke(refreshToken)
		response.addHeader(
			HttpHeaders.SET_COOKIE,
			refreshTokenCookieFactory.expire().toString(),
		)
		return ApiResponse.success(Unit)
	}
}
