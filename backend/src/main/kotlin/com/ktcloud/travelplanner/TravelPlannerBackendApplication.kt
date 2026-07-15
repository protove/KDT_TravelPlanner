package com.ktcloud.travelplanner

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.global.security.JwtProperties
import org.springframework.boot.autoconfigure.SpringBootApplication
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.boot.runApplication

@SpringBootApplication
@EnableConfigurationProperties(JwtProperties::class, OAuthFlowProperties::class)
class TravelPlannerBackendApplication

fun main(args: Array<String>) {
	runApplication<TravelPlannerBackendApplication>(*args)
}
