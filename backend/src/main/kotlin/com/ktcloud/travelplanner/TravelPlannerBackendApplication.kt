package com.ktcloud.travelplanner

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.auth.config.GoogleOAuthProperties
import com.ktcloud.travelplanner.auth.config.NaverOAuthProperties
import com.ktcloud.travelplanner.auth.config.OAuthHttpClientProperties
import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import com.ktcloud.travelplanner.global.security.JwtProperties
import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.ktcloud.travelplanner.user.config.ProfileImageStorageProperties
import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.boot.runApplication

@SpringBootApplication
@EnableConfigurationProperties(
	JwtProperties::class,
	OAuthFlowProperties::class,
	OAuthHttpClientProperties::class,
	GoogleOAuthProperties::class,
	NaverOAuthProperties::class,
	RefreshTokenProperties::class,
	ProfileImageStorageProperties::class,
	GooglePlacesProperties::class,
)
class TravelPlannerBackendApplication

fun main(args: Array<String>) {
	runApplication<TravelPlannerBackendApplication>(*args)
}
