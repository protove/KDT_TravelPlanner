package com.ktcloud.travelplanner.place.port

interface PlaceLocationCache {
	fun findLocation(googlePlaceId: String): PlaceLocation?

	fun saveLocation(googlePlaceId: String, location: PlaceLocation)
}
