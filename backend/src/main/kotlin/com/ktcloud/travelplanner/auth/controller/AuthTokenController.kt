package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import com.ktcloud.travelplanner.auth.service.IssuedRefreshToken
import com.ktcloud.travelplanner.auth.service.OAuthExchangeCodeService
import com.ktcloud.travelplanner.auth.service.RefreshTokenService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size
import org.springframework.http.HttpHeaders
import org.springframework.http.ResponseCookie
import org.springframework.web.bind.annotation.CookieValue
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.time.Instant

data class ExchangeAuthorizationCodeRequest(
	@field:NotBlank(message = "인증 코드를 입력해 주세요.")
	@field:Size(max = 256, message = "인증 코드는 256자 이하여야 합니다.")
	val code: String,
)

data class AccessTokenResponse(
	val accessToken: String,
	val tokenType: String,
	val expiresAt: Instant,
)

@RestController
@RequestMapping("/api/v1/auth/token")
class AuthTokenController(
	private val exchangeCodeService: OAuthExchangeCodeService,
	private val refreshTokenService: RefreshTokenService,
	private val refreshTokenProperties: RefreshTokenProperties,
) {
	@PostMapping("/exchange")
	fun exchange(
		@Valid @RequestBody request: ExchangeAuthorizationCodeRequest,
		response: HttpServletResponse,
	): ApiResponse<AccessTokenResponse> {
		val accessToken = exchangeCodeService.exchange(request.code)
		val refreshToken = refreshTokenService.issueForAccessToken(accessToken)
		response.addHeader(HttpHeaders.SET_COOKIE, createRefreshTokenCookie(refreshToken).toString())
		return accessTokenResponse(accessToken)
	}

	@PostMapping("/refresh")
	fun refresh(
		@CookieValue(name = REFRESH_TOKEN_COOKIE_NAME, required = false) refreshToken: String?,
	): ApiResponse<AccessTokenResponse> = accessTokenResponse(refreshTokenService.refresh(refreshToken))

	private fun accessTokenResponse(
		accessToken: IssuedAccessToken,
	): ApiResponse<AccessTokenResponse> =
		ApiResponse.success(
			AccessTokenResponse(
				accessToken = accessToken.value,
				tokenType = BEARER_TOKEN_TYPE,
				expiresAt = accessToken.expiresAt,
			),
		)

	private fun createRefreshTokenCookie(refreshToken: IssuedRefreshToken): ResponseCookie =
		ResponseCookie.from(REFRESH_TOKEN_COOKIE_NAME, refreshToken.value)
			.httpOnly(true)
			.secure(refreshTokenProperties.cookieSecure)
			.sameSite(refreshTokenProperties.cookieSameSite)
			.path(REFRESH_TOKEN_COOKIE_PATH)
			.maxAge(refreshTokenProperties.ttl)
			.build()

	companion object {
		private const val BEARER_TOKEN_TYPE = "Bearer"
		private const val REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
		private const val REFRESH_TOKEN_COOKIE_PATH = "/api/v1/auth"
	}
}
