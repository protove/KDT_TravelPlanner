package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.place.dto.PlaceSearchResultResponse
import com.ktcloud.travelplanner.place.port.PlaceSearchPort
import org.springframework.stereotype.Service
import java.util.Locale

@Service
class PlaceSearchService(
	private val placeSearchPort: PlaceSearchPort,
) {
	fun searchPlaces(
		query: String,
		countryCode: String,
	): List<PlaceSearchResultResponse> {
		val normalizedQuery = query.trim()
		val normalizedCountryCode = countryCode.trim().uppercase(Locale.ROOT)
		if (normalizedQuery.isEmpty() || normalizedQuery.length > QUERY_MAX_LENGTH) {
			throw InvalidPlaceSearchRequestException()
		}
		if (!COUNTRY_CODE_PATTERN.matches(normalizedCountryCode)) {
			throw InvalidPlaceSearchRequestException()
		}
		return placeSearchPort.searchPlaces(normalizedQuery, normalizedCountryCode)
			.map(PlaceSearchResultResponse::from)
	}

	companion object {
		private const val QUERY_MAX_LENGTH = 100
		private val COUNTRY_CODE_PATTERN = Regex("^[A-Z]{2}$")
	}
}

class InvalidPlaceSearchRequestException : DomainException(ErrorCode.INVALID_REQUEST)
