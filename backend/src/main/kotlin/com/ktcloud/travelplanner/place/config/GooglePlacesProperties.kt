package com.ktcloud.travelplanner.place.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.net.URI
import java.time.Duration

@ConfigurationProperties("app.external.google.places")
data class GooglePlacesProperties(
	val apiKey: String = "",
	val baseUrl: URI = URI.create("https://places.googleapis.com"),
	val connectTimeout: Duration = Duration.ofSeconds(2),
	val readTimeout: Duration = Duration.ofSeconds(3),
)
