package com.ktcloud.travelplanner.route.adapter

import com.ktcloud.travelplanner.global.external.externalHttpRequestFactory
import com.ktcloud.travelplanner.global.external.hasExternalTimeoutCause
import com.ktcloud.travelplanner.route.config.GoogleRoutesProperties
import com.ktcloud.travelplanner.route.exception.GoogleRoutesException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesNotConfiguredException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesProviderException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesQuotaExceededException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesTimeoutException
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculation
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
import com.ktcloud.travelplanner.route.port.RouteLegCalculation
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestClientResponseException
import java.math.BigDecimal

private data class GoogleComputeRoutesRequest(
	val origin: GoogleRouteWaypoint,
	val destination: GoogleRouteWaypoint,
	val intermediates: List<GoogleRouteWaypoint>,
	val travelMode: TransportationType,
	val languageCode: String = "ko-KR",
	val units: String = "METRIC",
)

private data class GoogleRouteWaypoint(
	val placeId: String,
)

private data class GoogleComputeRoutesResponse(
	val routes: List<GoogleRoute> = emptyList(),
)

private data class GoogleRoute(
	val distanceMeters: Long? = null,
	val duration: String? = null,
	val polyline: GoogleRoutePolyline? = null,
	val legs: List<GoogleRouteLeg> = emptyList(),
	val warnings: List<String> = emptyList(),
)

private data class GoogleRoutePolyline(
	val encodedPolyline: String? = null,
)

private data class GoogleRouteLeg(
	val distanceMeters: Long? = null,
	val duration: String? = null,
)

@Component
class GoogleRoutesAdapter(
	restClientBuilder: RestClient.Builder,
	private val properties: GoogleRoutesProperties,
) : RouteCalculationPort {
	private val restClient: RestClient = restClientBuilder.clone()
		.baseUrl(properties.baseUrl.toASCIIString())
		.requestFactory(externalHttpRequestFactory(properties.connectTimeout, properties.readTimeout))
		.build()

	override fun calculateRoute(
		googlePlaceIds: List<String>,
		transportationType: TransportationType,
	): RouteCalculation {
		require(googlePlaceIds.size >= 2) { "At least two Google Place IDs are required." }
		if (properties.apiKey.isBlank()) throw GoogleRoutesNotConfiguredException()
		val request = GoogleComputeRoutesRequest(
			origin = GoogleRouteWaypoint(googlePlaceIds.first()),
			destination = GoogleRouteWaypoint(googlePlaceIds.last()),
			intermediates = googlePlaceIds.drop(1).dropLast(1).map(::GoogleRouteWaypoint),
			travelMode = transportationType,
		)

		return try {
			val response = restClient.post()
				.uri("/directions/v2:computeRoutes")
				.contentType(MediaType.APPLICATION_JSON)
				.header(GOOGLE_API_KEY_HEADER, properties.apiKey)
				.header(GOOGLE_FIELD_MASK_HEADER, RESPONSE_FIELD_MASK)
				.body(request)
				.retrieve()
				.body(GoogleComputeRoutesResponse::class.java)
				?: throw GoogleRoutesProviderException()
			mapRoute(response, googlePlaceIds.size - 1)
		} catch (exception: GoogleRoutesException) {
			throw exception
		} catch (exception: ResourceAccessException) {
			if (exception.hasExternalTimeoutCause()) throw GoogleRoutesTimeoutException(exception)
			throw GoogleRoutesProviderException(exception)
		} catch (exception: RestClientResponseException) {
			if (exception.statusCode.value() == 429) throw GoogleRoutesQuotaExceededException(exception)
			throw GoogleRoutesProviderException(exception)
		} catch (exception: RestClientException) {
			throw GoogleRoutesProviderException(exception)
		} catch (exception: IllegalArgumentException) {
			throw GoogleRoutesProviderException(exception)
		}
	}

	private fun mapRoute(response: GoogleComputeRoutesResponse, expectedLegCount: Int): RouteCalculation {
		val route = response.routes.singleOrNull() ?: throw GoogleRoutesProviderException()
		if (route.legs.size != expectedLegCount) throw GoogleRoutesProviderException()
		return RouteCalculation(
			encodedPolyline = route.polyline?.encodedPolyline?.takeIf(String::isNotBlank),
			totalDistanceMeters = route.distanceMeters ?: throw GoogleRoutesProviderException(),
			totalDurationSeconds = parseDurationSeconds(route.duration),
			legs = route.legs.map { leg ->
				RouteLegCalculation(
					distanceMeters = leg.distanceMeters ?: throw GoogleRoutesProviderException(),
					durationSeconds = parseDurationSeconds(leg.duration),
				)
			},
			warnings = route.warnings,
		)
	}

	private fun parseDurationSeconds(duration: String?): Long {
		val seconds = duration?.takeIf { it.endsWith("s") }?.dropLast(1)
			?: throw GoogleRoutesProviderException()
		return try {
			BigDecimal(seconds).toLong()
		} catch (exception: ArithmeticException) {
			throw GoogleRoutesProviderException(exception)
		} catch (exception: NumberFormatException) {
			throw GoogleRoutesProviderException(exception)
		}
	}

	companion object {
		private const val GOOGLE_API_KEY_HEADER = "X-Goog-Api-Key"
		private const val GOOGLE_FIELD_MASK_HEADER = "X-Goog-FieldMask"
		private const val RESPONSE_FIELD_MASK =
			"routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline," +
				"routes.legs.distanceMeters,routes.legs.duration,routes.warnings"
	}
}
