package com.ktcloud.travelplanner.route.dto

import com.ktcloud.travelplanner.route.model.TransportationType
import java.util.UUID

data class TravelRouteResponse(
	val travelId: UUID,
	val dayNumber: Int,
	val transportationType: TransportationType,
	val encodedPolyline: String?,
	val totalDistanceMeters: Long,
	val totalDurationSeconds: Long,
	val legs: List<TravelRouteLegResponse>,
	val warnings: List<String>,
)

data class TravelRouteLegResponse(
	val fromTimelineItemId: UUID,
	val toTimelineItemId: UUID,
	val distanceMeters: Long,
	val durationSeconds: Long,
)
