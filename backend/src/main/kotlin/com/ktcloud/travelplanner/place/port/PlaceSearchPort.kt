package com.ktcloud.travelplanner.place.port

import java.math.BigDecimal

interface PlaceSearchPort {
	fun searchPlaces(
		query: String,
		countryCode: String,
	): List<PlaceSearchResult>
}

data class PlaceSearchResult(
	val placeId: String,
	val name: String,
	val latitude: BigDecimal,
	val longitude: BigDecimal,
	val rating: BigDecimal?,
)
