package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.place.port.PlaceLocationCache
import com.ktcloud.travelplanner.place.port.PlaceLocationPort
import org.springframework.stereotype.Service

@Service
class PlaceLocationService(
	private val placeLocationCache: PlaceLocationCache,
	private val placeLocationPort: PlaceLocationPort,
) {
	fun getLocation(googlePlaceId: String): PlaceLocation? {
		require(googlePlaceId.isNotBlank()) { "googlePlaceId must not be blank." }
		placeLocationCache.findLocation(googlePlaceId)?.let { return it }

		val location = placeLocationPort.findLocation(googlePlaceId) ?: return null
		placeLocationCache.saveLocation(googlePlaceId, location)
		return location
	}
}
