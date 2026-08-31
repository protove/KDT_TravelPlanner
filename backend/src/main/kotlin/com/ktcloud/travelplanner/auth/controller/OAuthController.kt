package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.service.OAuthLoginService
import io.swagger.v3.oas.annotations.security.SecurityRequirements
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.constraints.NotBlank
import org.springframework.http.HttpHeaders
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.validation.annotation.Validated
import org.springframework.web.bind.annotation.CookieValue
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/auth/oauth2")
@Validated
@SecurityRequirements
class OAuthController(
	private val loginService: OAuthLoginService,
	private val stateCookieFactory: OAuthStateCookieFactory,
) {
	// switchAccount=true는 "다른 계정으로 로그인" 링크 전용 — 세션이 남아있어도 프로바이더의
	// 계정 선택 화면을 강제한다. 기본 로그인 버튼은 이 파라미터 없이 호출해 항상 조용히 통과된다.
	@GetMapping("/{provider}")
	fun start(
		@PathVariable provider: String,
		@RequestParam(defaultValue = "false") switchAccount: Boolean,
	): ResponseEntity<Void> {
		val authorizationRedirect = loginService.createAuthorizationRedirect(provider, switchAccount)
		return ResponseEntity
			.status(HttpStatus.FOUND)
			.header(
				HttpHeaders.SET_COOKIE,
				stateCookieFactory.create(authorizationRedirect.state).toString(),
			)
			.location(authorizationRedirect.location)
			.build()
	}

	@GetMapping("/{provider}/callback")
	fun callback(
		@PathVariable provider: String,
		@RequestParam(required = false) code: String?,
		@RequestParam(required = false) error: String?,
		@RequestParam @NotBlank state: String,
		@CookieValue(name = OAuthStateCookieFactory.COOKIE_NAME, required = false) stateCookie: String?,
		response: HttpServletResponse,
	): ResponseEntity<Void> {
		response.addHeader(HttpHeaders.SET_COOKIE, stateCookieFactory.expire().toString())
		return ResponseEntity
			.status(HttpStatus.FOUND)
			.location(
				loginService.completeAuthorization(
					providerName = provider,
					authorizationCode = code,
					authorizationError = error,
					state = state,
					stateCookie = stateCookie,
				),
			)
			.build()
	}
}
