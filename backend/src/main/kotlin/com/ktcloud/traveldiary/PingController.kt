package com.ktcloud.traveldiary

import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

data class PingResponse(
	val status: String,
	val application: String,
	val profile: String,
)

@RestController
@RequestMapping("/api")
class PingController(
	private val environment: Environment,
) {
	@GetMapping("/ping")
	fun ping(): PingResponse = PingResponse(
		status = "ok",
		application = environment.getProperty("spring.application.name", "travel-diary-backend"),
		profile = environment.activeProfiles.firstOrNull() ?: "default",
	)
}
