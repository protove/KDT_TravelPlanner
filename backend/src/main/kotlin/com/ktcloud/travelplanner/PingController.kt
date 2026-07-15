package com.ktcloud.travelplanner

import org.springframework.core.env.Environment
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

data class PingResponse(
	val status: String,
	val application: String,
	val profile: String,
)

internal object PingResponseFactory {
	const val DEFAULT_APPLICATION_NAME = "travel-planner-backend"

	fun create(
		applicationName: String?,
		activeProfiles: Array<String>,
	): PingResponse = PingResponse(
		status = "ok",
		application = applicationName ?: DEFAULT_APPLICATION_NAME,
		profile = activeProfiles.firstOrNull() ?: "default",
	)
}

@RestController
@RequestMapping("/api")
class PingController(
	private val environment: Environment,
) {
	@GetMapping("/ping")
	fun ping(): PingResponse = PingResponseFactory.create(
		applicationName = environment.getProperty("spring.application.name"),
		activeProfiles = environment.activeProfiles,
	)
}
