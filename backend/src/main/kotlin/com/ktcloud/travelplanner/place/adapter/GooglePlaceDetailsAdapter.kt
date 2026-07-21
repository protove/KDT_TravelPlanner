package com.ktcloud.travelplanner.place.adapter

import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.place.port.PlaceLocationPort
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestClientResponseException
import java.math.BigDecimal

private data class GooglePlaceDetailsResponse(
	val location: GooglePlaceDetailsLocation? = null,
)

private data class GooglePlaceDetailsLocation(
	val latitude: BigDecimal? = null,
	val longitude: BigDecimal? = null,
)

@Component
class GooglePlaceDetailsAdapter(
	restClientBuilder: RestClient.Builder,
	private val properties: GooglePlacesProperties,
) : PlaceLocationPort {
	private val restClient: RestClient = restClientBuilder.clone()
		.baseUrl(properties.baseUrl.toASCIIString())
		.requestFactory(googlePlacesRequestFactory(properties))
		.build()

	override fun findLocation(googlePlaceId: String): PlaceLocation? {
		if (properties.apiKey.isBlank()) throw GooglePlacesNotConfiguredException()
		return try {
			val response = restClient.get()
				.uri { uriBuilder -> uriBuilder.path("/v1/places/{placeId}").build(googlePlaceId) }
				.header(GOOGLE_API_KEY_HEADER, properties.apiKey)
				.header(GOOGLE_FIELD_MASK_HEADER, RESPONSE_FIELD_MASK)
				.retrieve()
				.body(GooglePlaceDetailsResponse::class.java)
				?: throw GooglePlacesProviderException()
			mapLocation(response)
		} catch (exception: GooglePlacesException) {
			throw exception
		} catch (exception: ResourceAccessException) {
			throw exception.toGooglePlacesException()
		} catch (exception: RestClientResponseException) {
			when (exception.statusCode.value()) {
				404 -> null
				429 -> throw GooglePlacesQuotaExceededException(exception)
				else -> throw GooglePlacesProviderException(exception)
			}
		} catch (exception: RestClientException) {
			throw GooglePlacesProviderException(exception)
		} catch (exception: IllegalArgumentException) {
			throw GooglePlacesProviderException(exception)
		}
	}

	private fun mapLocation(response: GooglePlaceDetailsResponse): PlaceLocation {
		val latitude = response.location?.latitude ?: throw GooglePlacesProviderException()
		val longitude = response.location.longitude ?: throw GooglePlacesProviderException()
		return PlaceLocation(latitude, longitude)
	}

	companion object {
		private const val GOOGLE_API_KEY_HEADER = "X-Goog-Api-Key"
		private const val GOOGLE_FIELD_MASK_HEADER = "X-Goog-FieldMask"
		private const val RESPONSE_FIELD_MASK = "location"
	}
}
