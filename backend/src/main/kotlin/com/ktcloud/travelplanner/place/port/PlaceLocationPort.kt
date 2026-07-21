package com.ktcloud.travelplanner.place.port

import java.math.BigDecimal

interface PlaceLocationPort {
	fun findLocation(googlePlaceId: String): PlaceLocation?
}

data class PlaceLocation(
	val latitude: BigDecimal,
	val longitude: BigDecimal,
) {
	init {
		require(latitude in MIN_LATITUDE..MAX_LATITUDE) { "latitude must be between -90 and 90." }
		require(longitude in MIN_LONGITUDE..MAX_LONGITUDE) { "longitude must be between -180 and 180." }
	}

	companion object {
		private val MIN_LATITUDE = BigDecimal("-90")
		private val MAX_LATITUDE = BigDecimal("90")
		private val MIN_LONGITUDE = BigDecimal("-180")
		private val MAX_LONGITUDE = BigDecimal("180")
	}
}
