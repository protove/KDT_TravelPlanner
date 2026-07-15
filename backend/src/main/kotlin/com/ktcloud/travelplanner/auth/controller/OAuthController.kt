package com.ktcloud.travelplanner.auth.controller

import com.ktcloud.travelplanner.auth.service.OAuthLoginService
import jakarta.validation.constraints.NotBlank
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.validation.annotation.Validated
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/auth/oauth2")
@Validated
class OAuthController(
	private val loginService: OAuthLoginService,
) {
	@GetMapping("/{provider}")
	fun start(
		@PathVariable provider: String,
	): ResponseEntity<Void> = ResponseEntity
		.status(HttpStatus.FOUND)
		.location(loginService.createAuthorizationUrl(provider))
		.build()

	@GetMapping("/{provider}/callback")
	fun callback(
		@PathVariable provider: String,
		@RequestParam @NotBlank code: String,
		@RequestParam @NotBlank state: String,
	): ResponseEntity<Void> = ResponseEntity
		.status(HttpStatus.FOUND)
		.location(loginService.completeLogin(provider, code, state))
		.build()
}
