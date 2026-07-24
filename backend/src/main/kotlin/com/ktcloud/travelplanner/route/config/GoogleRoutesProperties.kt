package com.ktcloud.travelplanner.route.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.net.URI
import java.time.Duration

@ConfigurationProperties("app.external.google.routes")
data class GoogleRoutesProperties(
	val apiKey: String = "",
	val baseUrl: URI = URI.create("https://routes.googleapis.com"),
	val connectTimeout: Duration = Duration.ofSeconds(2),
	val readTimeout: Duration = Duration.ofSeconds(5),
)
