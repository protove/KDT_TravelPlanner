package com.ktcloud.travelplanner.place.dto

import com.ktcloud.travelplanner.place.port.PlaceSearchResult
import java.math.BigDecimal

data class PlaceSearchResultResponse(
	val placeId: String,
	val name: String,
	val latitude: BigDecimal,
	val longitude: BigDecimal,
	val rating: BigDecimal?,
) {
	companion object {
		fun from(result: PlaceSearchResult): PlaceSearchResultResponse = PlaceSearchResultResponse(
			placeId = result.placeId,
			name = result.name,
			latitude = result.latitude,
			longitude = result.longitude,
			rating = result.rating,
		)
	}
}
