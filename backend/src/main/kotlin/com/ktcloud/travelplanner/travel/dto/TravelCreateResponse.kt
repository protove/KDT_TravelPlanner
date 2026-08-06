package com.ktcloud.travelplanner.travel.dto

import com.ktcloud.travelplanner.travel.model.Travel
import java.util.UUID

data class TravelCreateResponse(
	val travelId: UUID,
) {
	companion object {
		fun from(travel: Travel): TravelCreateResponse = TravelCreateResponse(travel.id)
	}
}
