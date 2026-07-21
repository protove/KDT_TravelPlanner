package com.ktcloud.travelplanner.place.dto

import java.util.UUID

data class TravelMapPointsResponse(
	val travelId: UUID,
	val dayNumber: Int,
	val points: List<TravelMapPointResponse>,
	val unmappedTimelineItemIds: List<UUID>,
	val unresolvedTimelineItemIds: List<UUID>,
)
