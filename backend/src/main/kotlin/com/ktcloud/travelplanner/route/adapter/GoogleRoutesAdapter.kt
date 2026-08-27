package com.ktcloud.travelplanner.route.adapter

import com.ktcloud.travelplanner.global.external.externalHttpRequestFactory
import com.ktcloud.travelplanner.global.external.hasExternalTimeoutCause
import com.ktcloud.travelplanner.route.config.GoogleRoutesProperties
import com.ktcloud.travelplanner.route.exception.GoogleRoutesNotConfiguredException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesProviderException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesQuotaExceededException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesTimeoutException
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculation
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
import com.ktcloud.travelplanner.route.port.RouteCalculationWaypoint
import com.ktcloud.travelplanner.route.port.RouteLegCalculation
import org.slf4j.LoggerFactory
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.client.ResourceAccessException
import org.springframework.web.client.RestClient
import org.springframework.web.client.RestClientException
import org.springframework.web.client.RestClientResponseException
import java.math.BigDecimal

private const val TRANSIT_TRAVEL_MODE =
    "TRANSIT"

/*
 * ======================================================
 * 기존 GET /routes 요청
 * ======================================================
 */

private data class GooglePlaceIdComputeRoutesRequest(
    val origin: GooglePlaceIdWaypoint,
    val destination: GooglePlaceIdWaypoint,
    val intermediates: List<GooglePlaceIdWaypoint>,
    val travelMode: TransportationType,
    val languageCode: String = "ko-KR",
    val units: String = "METRIC",
)

private data class GooglePlaceIdWaypoint(
    val placeId: String,
)

/*
 * ======================================================
 * SCRUM-56 TRANSIT Preview
 * ======================================================
 */

private data class GoogleTransitPlaceIdRequest(
    val origin: GooglePlaceIdWaypoint,
    val destination: GooglePlaceIdWaypoint,
    val travelMode: String = TRANSIT_TRAVEL_MODE,
    val languageCode: String = "ko-KR",
    val units: String = "METRIC",
)

private data class GoogleTransitCoordinateRequest(
    val origin: GoogleCoordinateWaypoint,
    val destination: GoogleCoordinateWaypoint,
    val travelMode: String = TRANSIT_TRAVEL_MODE,
    val languageCode: String = "ko-KR",
    val units: String = "METRIC",
)

private data class GoogleCoordinateWaypoint(
    val location: GoogleRouteLocation,
)

private data class GoogleRouteLocation(
    val latLng: GoogleRouteLatLng,
)

private data class GoogleRouteLatLng(
    val latitude: Double,
    val longitude: Double,
)

/*
 * ======================================================
 * Google Routes 응답
 * ======================================================
 */

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

private data class TransitSegmentCalculation(
    val encodedPolyline: String,
    val distanceMeters: Long,
    val durationSeconds: Long,
    val warnings: List<String>,
)

@Component
class GoogleRoutesAdapter(
    restClientBuilder: RestClient.Builder,
    private val properties: GoogleRoutesProperties,
) : RouteCalculationPort {

    private val logger =
        LoggerFactory.getLogger(
            GoogleRoutesAdapter::class.java,
        )

    private val restClient: RestClient =
        restClientBuilder
            .clone()
            .baseUrl(
                properties.baseUrl.toASCIIString(),
            )
            .requestFactory(
                externalHttpRequestFactory(
                    properties.connectTimeout,
                    properties.readTimeout,
                ),
            )
            .build()

    /*
     * ======================================================
     * 기존 GET /routes
     * ======================================================
     */

    override fun calculateRoute(
        googlePlaceIds: List<String>,
        transportationType: TransportationType,
    ): RouteCalculation {
        require(
            googlePlaceIds.size >= 2,
        ) {
            "At least two Google Place IDs are required."
        }

        validateConfigured()

        val normalizedPlaceIds =
            googlePlaceIds.map {
                it.trim()
            }

        if (
            normalizedPlaceIds.any {
                it.isBlank()
            }
        ) {
            throw GoogleRoutesProviderException()
        }

        val request =
            GooglePlaceIdComputeRoutesRequest(
                origin =
                    GooglePlaceIdWaypoint(
                        normalizedPlaceIds.first(),
                    ),

                destination =
                    GooglePlaceIdWaypoint(
                        normalizedPlaceIds.last(),
                    ),

                intermediates =
                    normalizedPlaceIds
                        .drop(1)
                        .dropLast(1)
                        .map(
                            ::GooglePlaceIdWaypoint,
                        ),

                travelMode =
                    transportationType,
            )

        val response =
            requestRoutes(
                request,
            )

        if (
            response.routes.isEmpty()
        ) {
            logger.warn(
                "Google Routes returned no route for Place ID waypoints. waypointCount={}, transportationType={}",
                normalizedPlaceIds.size,
                transportationType,
            )

            return noRouteCalculation()
        }

        return mapRoute(
            response =
                response,

            expectedLegCount =
                normalizedPlaceIds.size - 1,
        )
    }

    /*
     * ======================================================
     * SCRUM-56 TRANSIT Preview
     * ======================================================
     *
     * visitOrder:
     *
     * A -> B -> C -> D
     *
     * Google 호출:
     *
     * A -> B
     * B -> C
     * C -> D
     *
     * TRANSIT에서는 intermediate waypoint를 사용하지 않는다.
     */

    override fun calculatePreviewRoute(
        waypoints: List<RouteCalculationWaypoint>,
    ): RouteCalculation {
        require(
            waypoints.size >= 2,
        ) {
            "At least two route waypoints are required."
        }

        validateConfigured()

        val normalizedWaypoints =
            waypoints.map { waypoint ->
                waypoint.copy(
                    googlePlaceId =
                        waypoint.googlePlaceId.trim(),
                )
            }

        if (
            normalizedWaypoints.any { waypoint ->
                waypoint.googlePlaceId.isBlank() ||
                    waypoint.latitude !in -90.0..90.0 ||
                    waypoint.longitude !in -180.0..180.0
            }
        ) {
            throw GoogleRoutesProviderException()
        }

        val segments =
            mutableListOf<
                TransitSegmentCalculation
            >()

        for (
            index in
            0 until normalizedWaypoints.lastIndex
        ) {
            val origin =
                normalizedWaypoints[
                    index
                ]

            val destination =
                normalizedWaypoints[
                    index + 1
                ]

            val segment =
                calculateTransitSegment(
                    origin =
                        origin,

                    destination =
                        destination,

                    segmentIndex =
                        index,
                )

            if (
                segment ==
                null
            ) {
                logger.warn(
                    "Google Routes returned no TRANSIT route for preview segment. segmentIndex={}, originPlaceId={}, destinationPlaceId={}",
                    index,
                    origin.googlePlaceId,
                    destination.googlePlaceId,
                )

                return noRouteCalculation()
            }

            segments +=
                segment
        }

        val encodedPolylines =
            segments.map {
                it.encodedPolyline
            }

        val totalDistanceMeters =
            segments.sumOf {
                it.distanceMeters
            }

        val totalDurationSeconds =
            segments.sumOf {
                it.durationSeconds
            }

        val legs =
            segments.map { segment ->
                RouteLegCalculation(
                    distanceMeters =
                        segment.distanceMeters,

                    durationSeconds =
                        segment.durationSeconds,
                )
            }

        val warnings =
            segments
                .flatMap {
                    it.warnings
                }
                .distinct()

        logger.info(
            "Google Routes TRANSIT preview succeeded. waypointCount={}, segmentCount={}, totalDistanceMeters={}, totalDurationSeconds={}",
            normalizedWaypoints.size,
            segments.size,
            totalDistanceMeters,
            totalDurationSeconds,
        )

        return RouteCalculation(
            encodedPolyline =
                encodedPolylines
                    .singleOrNull(),

            encodedPolylines =
                encodedPolylines,

            totalDistanceMeters =
                totalDistanceMeters,

            totalDurationSeconds =
                totalDurationSeconds,

            legs =
                legs,

            warnings =
                warnings,
        )
    }

    /*
     * ======================================================
     * TRANSIT 한 구간
     * ======================================================
     */

    private fun calculateTransitSegment(
        origin: RouteCalculationWaypoint,
        destination: RouteCalculationWaypoint,
        segmentIndex: Int,
    ): TransitSegmentCalculation? {
        /*
         * 1차:
         * Place ID.
         */
        val placeIdRequest =
            GoogleTransitPlaceIdRequest(
                origin =
                    GooglePlaceIdWaypoint(
                        origin.googlePlaceId,
                    ),

                destination =
                    GooglePlaceIdWaypoint(
                        destination.googlePlaceId,
                    ),
            )

        val placeIdResponse =
            requestRoutes(
                placeIdRequest,
            )

        if (
            placeIdResponse.routes.isNotEmpty()
        ) {
            return mapTransitSegment(
                response =
                    placeIdResponse,

                segmentIndex =
                    segmentIndex,
            )
        }

        /*
         * 2차:
         * 좌표 fallback.
         */
        logger.info(
            "Google Routes returned no TRANSIT route for Place IDs. Retrying with coordinates. segmentIndex={}",
            segmentIndex,
        )

        val coordinateRequest =
            GoogleTransitCoordinateRequest(
                origin =
                    origin
                        .toGoogleCoordinateWaypoint(),

                destination =
                    destination
                        .toGoogleCoordinateWaypoint(),
            )

        val coordinateResponse =
            requestRoutes(
                coordinateRequest,
            )

        if (
            coordinateResponse.routes.isEmpty()
        ) {
            return null
        }

        logger.info(
            "Google Routes TRANSIT coordinate fallback succeeded. segmentIndex={}",
            segmentIndex,
        )

        return mapTransitSegment(
            response =
                coordinateResponse,

            segmentIndex =
                segmentIndex,
        )
    }

    /*
     * ======================================================
     * TRANSIT 응답 변환
     * ======================================================
     */

    private fun mapTransitSegment(
        response: GoogleComputeRoutesResponse,
        segmentIndex: Int,
    ): TransitSegmentCalculation {
        if (
            response.routes.size !=
            1
        ) {
            logger.error(
                "Google Routes returned unexpected TRANSIT route count. segmentIndex={}, expected=1, actual={}",
                segmentIndex,
                response.routes.size,
            )

            throw GoogleRoutesProviderException()
        }

        val route =
            response.routes.single()

        val distanceMeters =
            route.distanceMeters
                ?: run {
                    logger.error(
                        "Google Routes TRANSIT response is missing distanceMeters. segmentIndex={}",
                        segmentIndex,
                    )

                    throw GoogleRoutesProviderException()
                }

        val encodedPolyline =
            route.polyline
                ?.encodedPolyline
                ?.takeIf(
                    String::isNotBlank,
                )
                ?: run {
                    logger.error(
                        "Google Routes TRANSIT response is missing encodedPolyline. segmentIndex={}",
                        segmentIndex,
                    )

                    throw GoogleRoutesProviderException()
                }

        val durationSeconds =
            parseDurationSeconds(
                duration =
                    route.duration,

                fieldName =
                    "transitSegment[$segmentIndex]",
            )

        return TransitSegmentCalculation(
            encodedPolyline =
                encodedPolyline,

            distanceMeters =
                distanceMeters,

            durationSeconds =
                durationSeconds,

            warnings =
                route.warnings,
        )
    }

    /*
     * ======================================================
     * Google HTTP
     * ======================================================
     */

    private fun requestRoutes(
        request: Any,
    ): GoogleComputeRoutesResponse {
        return try {
            restClient
                .post()
                .uri(
                    "/directions/v2:computeRoutes",
                )
                .contentType(
                    MediaType.APPLICATION_JSON,
                )
                .header(
                    GOOGLE_API_KEY_HEADER,
                    properties.apiKey,
                )
                .header(
                    GOOGLE_FIELD_MASK_HEADER,
                    RESPONSE_FIELD_MASK,
                )
                .body(
                    request,
                )
                .retrieve()
                .body(
                    GoogleComputeRoutesResponse::class.java,
                )
                ?: run {
                    logger.error(
                        "Google Routes returned an empty response body.",
                    )

                    throw GoogleRoutesProviderException()
                }
        } catch (
            exception: ResourceAccessException,
        ) {
            if (
                exception.hasExternalTimeoutCause()
            ) {
                logger.error(
                    "Google Routes request timed out.",
                    exception,
                )

                throw GoogleRoutesTimeoutException(
                    exception,
                )
            }

            logger.error(
                "Google Routes network request failed.",
                exception,
            )

            throw GoogleRoutesProviderException(
                exception,
            )
        } catch (
            exception: RestClientResponseException,
        ) {
            logger.error(
                "Google Routes API rejected request. status={}, body={}",
                exception.statusCode.value(),
                exception.responseBodyAsString,
            )

            if (
                exception.statusCode.value() ==
                429
            ) {
                throw GoogleRoutesQuotaExceededException(
                    exception,
                )
            }

            throw GoogleRoutesProviderException(
                exception,
            )
        } catch (
            exception: RestClientException,
        ) {
            logger.error(
                "Google Routes RestClient request failed.",
                exception,
            )

            throw GoogleRoutesProviderException(
                exception,
            )
        } catch (
            exception: IllegalArgumentException,
        ) {
            logger.error(
                "Google Routes request was invalid.",
                exception,
            )

            throw GoogleRoutesProviderException(
                exception,
            )
        }
    }

    /*
     * ======================================================
     * 기존 GET /routes 응답 변환
     * ======================================================
     */

    private fun mapRoute(
        response: GoogleComputeRoutesResponse,
        expectedLegCount: Int,
    ): RouteCalculation {
        if (
            response.routes.size !=
            1
        ) {
            logger.error(
                "Google Routes returned unexpected route count. expected=1, actual={}",
                response.routes.size,
            )

            throw GoogleRoutesProviderException()
        }

        val route =
            response.routes.single()

        if (
            route.legs.size !=
            expectedLegCount
        ) {
            logger.error(
                "Google Routes returned unexpected leg count. expected={}, actual={}",
                expectedLegCount,
                route.legs.size,
            )

            throw GoogleRoutesProviderException()
        }

        val totalDistanceMeters =
            route.distanceMeters
                ?: run {
                    logger.error(
                        "Google Routes response is missing routes.distanceMeters.",
                    )

                    throw GoogleRoutesProviderException()
                }

        val encodedPolyline =
            route.polyline
                ?.encodedPolyline
                ?.takeIf(
                    String::isNotBlank,
                )
                ?: run {
                    logger.error(
                        "Google Routes response is missing routes.polyline.encodedPolyline.",
                    )

                    throw GoogleRoutesProviderException()
                }

        return RouteCalculation(
            encodedPolyline =
                encodedPolyline,

            encodedPolylines =
                listOf(
                    encodedPolyline,
                ),

            totalDistanceMeters =
                totalDistanceMeters,

            totalDurationSeconds =
                parseDurationSeconds(
                    duration =
                        route.duration,

                    fieldName =
                        "route",
                ),

            legs =
                route.legs.mapIndexed {
                        index,
                        leg,
                    ->

                    val distanceMeters =
                        leg.distanceMeters
                            ?: run {
                                logger.error(
                                    "Google Routes response leg is missing distanceMeters. legIndex={}",
                                    index,
                                )

                                throw GoogleRoutesProviderException()
                            }

                    RouteLegCalculation(
                        distanceMeters =
                            distanceMeters,

                        durationSeconds =
                            parseDurationSeconds(
                                duration =
                                    leg.duration,

                                fieldName =
                                    "leg[$index]",
                            ),
                    )
                },

            warnings =
                route.warnings,
        )
    }

    private fun noRouteCalculation() =
        RouteCalculation(
            encodedPolyline =
                null,

            encodedPolylines =
                emptyList(),

            totalDistanceMeters =
                0,

            totalDurationSeconds =
                0,

            legs =
                emptyList(),

            warnings =
                listOf(
                    NO_ROUTE_FOUND_WARNING,
                ),
        )

    private fun RouteCalculationWaypoint
        .toGoogleCoordinateWaypoint() =
        GoogleCoordinateWaypoint(
            location =
                GoogleRouteLocation(
                    latLng =
                        GoogleRouteLatLng(
                            latitude =
                                latitude,

                            longitude =
                                longitude,
                        ),
                ),
        )

    private fun validateConfigured() {
        if (
            properties.apiKey.isBlank()
        ) {
            throw GoogleRoutesNotConfiguredException()
        }
    }

    private fun parseDurationSeconds(
        duration: String?,
        fieldName: String,
    ): Long {
        val seconds =
            duration
                ?.takeIf {
                    it.endsWith("s")
                }
                ?.dropLast(1)
                ?: run {
                    logger.error(
                        "Google Routes returned invalid duration. field={}, value={}",
                        fieldName,
                        duration,
                    )

                    throw GoogleRoutesProviderException()
                }

        return try {
            BigDecimal(
                seconds,
            ).toLong()
        } catch (
            exception: ArithmeticException,
        ) {
            logger.error(
                "Google Routes duration could not be converted. field={}, value={}",
                fieldName,
                duration,
                exception,
            )

            throw GoogleRoutesProviderException(
                exception,
            )
        } catch (
            exception: NumberFormatException,
        ) {
            logger.error(
                "Google Routes duration has invalid number format. field={}, value={}",
                fieldName,
                duration,
                exception,
            )

            throw GoogleRoutesProviderException(
                exception,
            )
        }
    }

    companion object {
        private const val GOOGLE_API_KEY_HEADER =
            "X-Goog-Api-Key"

        private const val GOOGLE_FIELD_MASK_HEADER =
            "X-Goog-FieldMask"

        private const val NO_ROUTE_FOUND_WARNING =
            "NO_ROUTE_FOUND"

        private const val RESPONSE_FIELD_MASK =
            "routes.distanceMeters," +
                "routes.duration," +
                "routes.polyline.encodedPolyline," +
                "routes.legs.distanceMeters," +
                "routes.legs.duration," +
                "routes.warnings"
    }
}