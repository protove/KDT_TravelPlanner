package com.ktcloud.travelplanner.route.dto

enum class TravelRoutePreviewTransportationType {
    TRANSIT,
}

data class TravelRoutePreviewRequest(
    val dayNumber: Int,
    val transportationType: TravelRoutePreviewTransportationType,
    val waypoints: List<TravelRoutePreviewWaypointRequest>,
)

data class TravelRoutePreviewWaypointRequest(
    val googlePlaceId: String,
    val latitude: Double,
    val longitude: Double,
)

data class TravelRoutePreviewResponse(
    val dayNumber: Int,
    val transportationType: TravelRoutePreviewTransportationType,
    val encodedPolyline: String?,
    val encodedPolylines: List<String>,
    val totalDistanceMeters: Long,
    val totalDurationSeconds: Long,
    val warnings: List<String>,
)