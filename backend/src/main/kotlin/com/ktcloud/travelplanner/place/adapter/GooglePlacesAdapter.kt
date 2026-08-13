package com.ktcloud.travelplanner.place.adapter

import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.exception.ExternalServiceException
import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.ktcloud.travelplanner.place.port.PlaceSearchPort
import com.ktcloud.travelplanner.place.port.PlaceSearchResult
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestClientResponseException
import java.math.BigDecimal

private data class GooglePlaceSearchRequest(
	val textQuery: String,
	val languageCode: String = "ko",
	val regionCode: String,
)

private data class GooglePlaceSearchResponse(
	val places: List<GooglePlace> = emptyList(),
)

private data class GooglePlace(
	val id: String? = null,
	val displayName: GoogleDisplayName? = null,
	val location: GoogleLocation? = null,
	val rating: BigDecimal? = null,
)

private data class GoogleDisplayName(
	val text: String? = null,
	val languageCode: String? = null,
)

private data class GoogleLocation(
	val latitude: BigDecimal? = null,
	val longitude: BigDecimal? = null,
)

@Component
class GooglePlacesAdapter(
	restClientBuilder: RestClient.Builder,
	private val properties: GooglePlacesProperties,
) : PlaceSearchPort {
	private val restClient: RestClient = restClientBuilder.clone()
		.baseUrl(properties.baseUrl.toASCIIString())
		.requestFactory(googlePlacesRequestFactory(properties))
		.build()

	override fun searchPlaces(
		query: String,
		countryCode: String,
	): List<PlaceSearchResult> {
		if (properties.apiKey.isBlank()) throw GooglePlacesNotConfiguredException()
		return try {
			val response = restClient.post()
				.uri("/v1/places:searchText")
				.contentType(MediaType.APPLICATION_JSON)
				.header(GOOGLE_API_KEY_HEADER, properties.apiKey)
				.header(GOOGLE_FIELD_MASK_HEADER, RESPONSE_FIELD_MASK)
				.body(
					GooglePlaceSearchRequest(
						textQuery = query,
						regionCode = countryCode,
					),
				)
				.retrieve()
				.body(GooglePlaceSearchResponse::class.java)
				?: throw GooglePlacesProviderException()
			response.places.map(::mapPlace)
		} catch (exception: GooglePlacesException) {
			throw exception
		} catch (exception: ResourceAccessException) {
			throw exception.toGooglePlacesException()
		} catch (exception: RestClientResponseException) {
			if (exception.statusCode.value() == 429) throw GooglePlacesQuotaExceededException(exception)
			throw GooglePlacesProviderException(exception)
		} catch (exception: RestClientException) {
			throw GooglePlacesProviderException(exception)
		}
	}

	private fun mapPlace(place: GooglePlace): PlaceSearchResult {
		val placeId = place.id?.takeIf(String::isNotBlank) ?: throw GooglePlacesProviderException()
		val name = place.displayName?.text?.takeIf(String::isNotBlank) ?: throw GooglePlacesProviderException()
		val latitude = place.location?.latitude ?: throw GooglePlacesProviderException()
		val longitude = place.location.longitude ?: throw GooglePlacesProviderException()
		return PlaceSearchResult(placeId, name, latitude, longitude, place.rating)
	}

	companion object {
		private const val GOOGLE_API_KEY_HEADER = "X-Goog-Api-Key"
		private const val GOOGLE_FIELD_MASK_HEADER = "X-Goog-FieldMask"
		private const val RESPONSE_FIELD_MASK =
			"places.id,places.displayName.text,places.location,places.rating"
	}
}

sealed class GooglePlacesException(errorCode: ErrorCode, cause: Throwable? = null) :
	ExternalServiceException(errorCode, cause = cause)

class GooglePlacesNotConfiguredException : GooglePlacesException(ErrorCode.GOOGLE_PLACES_NOT_CONFIGURED)

class GooglePlacesTimeoutException(cause: Throwable) : GooglePlacesException(ErrorCode.GOOGLE_PLACES_TIMEOUT, cause)

class GooglePlacesQuotaExceededException(cause: Throwable) :
	GooglePlacesException(ErrorCode.GOOGLE_PLACES_QUOTA_EXCEEDED, cause)

class GooglePlacesProviderException(cause: Throwable? = null) :
	GooglePlacesException(ErrorCode.GOOGLE_PLACES_ERROR, cause)
