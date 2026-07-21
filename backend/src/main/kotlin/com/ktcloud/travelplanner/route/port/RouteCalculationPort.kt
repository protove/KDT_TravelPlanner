package com.ktcloud.travelplanner.route.port

import com.ktcloud.travelplanner.route.model.TransportationType

interface RouteCalculationPort {
	fun calculateRoute(
		googlePlaceIds: List<String>,
		transportationType: TransportationType,
	): RouteCalculation
}

data class RouteCalculation(
	val encodedPolyline: String?,
	val totalDistanceMeters: Long,
	val totalDurationSeconds: Long,
	val legs: List<RouteLegCalculation>,
	val warnings: List<String>,
) {
	init {
		require(totalDistanceMeters >= 0) { "totalDistanceMeters must not be negative." }
		require(totalDurationSeconds >= 0) { "totalDurationSeconds must not be negative." }
	}
}

data class RouteLegCalculation(
	val distanceMeters: Long,
	val durationSeconds: Long,
) {
	init {
		require(distanceMeters >= 0) { "distanceMeters must not be negative." }
		require(durationSeconds >= 0) { "durationSeconds must not be negative." }
	}
}
