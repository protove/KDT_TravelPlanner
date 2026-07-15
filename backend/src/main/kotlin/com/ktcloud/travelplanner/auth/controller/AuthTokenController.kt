package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.service.OAuthExchangeCodeService
import com.ktcloud.travelplanner.auth.service.RefreshTokenService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size
import org.springframework.http.HttpHeaders
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
	private val refreshTokenCookieFactory: RefreshTokenCookieFactory,
) {
	@PostMapping("/exchange")
	fun exchange(
		@Valid @RequestBody request: ExchangeAuthorizationCodeRequest,
		response: HttpServletResponse,
	): ApiResponse<AccessTokenResponse> {
		val accessToken = exchangeCodeService.exchange(request.code)
		val refreshToken = refreshTokenService.issueForAccessToken(accessToken)
		response.addHeader(
			HttpHeaders.SET_COOKIE,
			refreshTokenCookieFactory.create(refreshToken.value).toString(),
		)
		return accessTokenResponse(accessToken)
	}

	@PostMapping("/refresh")
	fun refresh(
		@CookieValue(name = RefreshTokenCookieFactory.COOKIE_NAME, required = false) refreshToken: String?,
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

	companion object {
		private const val BEARER_TOKEN_TYPE = "Bearer"
	}
}
