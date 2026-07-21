package com.ktcloud.travelplanner.place.dto

import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import java.math.BigDecimal
import java.util.UUID

data class TravelMapPointResponse(
	val timelineItemId: UUID,
	val visitOrder: Int,
	val name: String,
	val googlePlaceId: String,
	val latitude: BigDecimal,
	val longitude: BigDecimal,
) {
	companion object {
		fun from(timelineItem: TimelineItem, location: PlaceLocation): TravelMapPointResponse =
			TravelMapPointResponse(
				timelineItemId = timelineItem.id,
				visitOrder = timelineItem.visitOrder.toInt(),
				name = timelineItem.name,
				googlePlaceId = requireNotNull(timelineItem.googlePlaceId),
				latitude = location.latitude,
				longitude = location.longitude,
			)
	}
}
