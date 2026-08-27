package com.ktcloud.travelplanner.route.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.route.dto.TravelRouteLegResponse
import com.ktcloud.travelplanner.route.dto.TravelRoutePreviewRequest
import com.ktcloud.travelplanner.route.dto.TravelRoutePreviewResponse
import com.ktcloud.travelplanner.route.dto.TravelRoutePreviewTransportationType
import com.ktcloud.travelplanner.route.dto.TravelRouteResponse
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
import com.ktcloud.travelplanner.route.port.RouteCalculationWaypoint
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TravelRouteService(
    private val travelRepository: TravelRepository,
    private val travelMemberRepository: TravelMemberRepository,
    private val timelineItemRepository: TimelineItemRepository,
    private val routeCalculationPort: RouteCalculationPort,
) {

    /*
     * ======================================================
     * 기존 GET /routes
     * ======================================================
     */

    @Transactional(readOnly = true)
    fun getRoute(
        travelId: UUID,
        requesterId: UUID,
        dayNumber: Int,
        transportationType: TransportationType,
    ): TravelRouteResponse {
        val travel =
            travelRepository
                .findById(
                    travelId,
                )
                .orElseThrow(
                    ::RouteTravelNotFoundException,
                )

        validateReadPermission(
            travel,
            requesterId,
        )

        validateDayNumber(
            travel,
            dayNumber,
        )

        val waypoints =
            timelineItemRepository
                .findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(
                    travelId,
                    dayNumber.toShort(),
                )
                .mapNotNull { timelineItem ->
                    timelineItem.googlePlaceId
                        ?.takeIf(
                            String::isNotBlank,
                        )
                        ?.let { placeId ->
                            RouteWaypoint(
                                timelineItemId =
                                    timelineItem.id,

                                googlePlaceId =
                                    placeId,
                            )
                        }
                }

        validateWaypointCount(
            waypoints.size,
        )

        if (
            waypoints.size <=
            1
        ) {
            return emptyRoute(
                travelId =
                    travelId,

                dayNumber =
                    dayNumber,

                transportationType =
                    transportationType,
            )
        }

        val calculation =
            routeCalculationPort
                .calculateRoute(
                    googlePlaceIds =
                        waypoints.map {
                            it.googlePlaceId
                        },

                    transportationType =
                        transportationType,
                )

        /*
         * 기존 GET route는 실제 route가 있는 경우
         * Google legs 개수를 검증한다.
         *
         * NO_ROUTE_FOUND의 경우에는 legs가 비어있다.
         */
        if (
            calculation.encodedPolyline !=
            null &&
            calculation.legs.size !=
            waypoints.size - 1
        ) {
            throw InvalidRouteCalculationException()
        }

        val legs =
            if (
                calculation.encodedPolyline ==
                null
            ) {
                emptyList()
            } else {
                calculation.legs
                    .mapIndexed {
                            index,
                            leg,
                        ->

                        TravelRouteLegResponse(
                            fromTimelineItemId =
                                waypoints[index]
                                    .timelineItemId,

                            toTimelineItemId =
                                waypoints[index + 1]
                                    .timelineItemId,

                            distanceMeters =
                                leg.distanceMeters,

                            durationSeconds =
                                leg.durationSeconds,
                        )
                    }
            }

        return TravelRouteResponse(
            travelId =
                travelId,

            dayNumber =
                dayNumber,

            transportationType =
                transportationType,

            encodedPolyline =
                calculation.encodedPolyline,

            totalDistanceMeters =
                calculation.totalDistanceMeters,

            totalDurationSeconds =
                calculation.totalDurationSeconds,

            legs =
                legs,

            warnings =
                calculation.warnings,
        )
    }

    /*
     * ======================================================
     * SCRUM-56 POST /routes/preview
     * ======================================================
     *
     * 프론트에서:
     *
     * 현재 날짜
     * + assigned만
     * + visitOrder 순서
     *
     * 로 전달한다.
     *
     * GoogleRoutesAdapter에서:
     *
     * A -> B
     * B -> C
     * C -> D
     *
     * TRANSIT으로 각각 계산한다.
     */

    @Transactional(readOnly = true)
    fun previewRoute(
        travelId: UUID,
        requesterId: UUID,
        request: TravelRoutePreviewRequest,
    ): TravelRoutePreviewResponse {
        val travel =
            travelRepository
                .findById(
                    travelId,
                )
                .orElseThrow(
                    ::RouteTravelNotFoundException,
                )

        validateReadPermission(
            travel,
            requesterId,
        )

        validateDayNumber(
            travel,
            request.dayNumber,
        )

        validateWaypointCount(
            request.waypoints.size,
        )

        if (
            request.waypoints.any { waypoint ->
                waypoint.googlePlaceId
                    .isBlank() ||
                    waypoint.latitude !in
                    -90.0..90.0 ||
                    waypoint.longitude !in
                    -180.0..180.0
            }
        ) {
            throw InvalidRouteWaypointException()
        }

        if (
            request.waypoints.size <=
            1
        ) {
            return emptyPreviewRoute(
                dayNumber =
                    request.dayNumber,

                transportationType =
                    request.transportationType,
            )
        }

        val calculation =
            routeCalculationPort
                .calculatePreviewRoute(
                    waypoints =
                        request.waypoints
                            .map { waypoint ->
                                RouteCalculationWaypoint(
                                    googlePlaceId =
                                        waypoint.googlePlaceId
                                            .trim(),

                                    latitude =
                                        waypoint.latitude,

                                    longitude =
                                        waypoint.longitude,
                                )
                            },
                )

        /*
         * 경로가 있는 경우:
         *
         * 4개 장소면
         * polyline 3개
         * leg 3개
         *
         * 가 나와야 한다.
         */
        if (
            calculation.encodedPolylines
                .isNotEmpty() &&
            (
                calculation.encodedPolylines.size !=
                    request.waypoints.size - 1 ||
                    calculation.legs.size !=
                    request.waypoints.size - 1
            )
        ) {
            throw InvalidRouteCalculationException()
        }

        return TravelRoutePreviewResponse(
            dayNumber =
                request.dayNumber,

            transportationType =
                request.transportationType,

            encodedPolyline =
                calculation.encodedPolyline,

            encodedPolylines =
                calculation.encodedPolylines,

            totalDistanceMeters =
                calculation.totalDistanceMeters,

            totalDurationSeconds =
                calculation.totalDurationSeconds,

            warnings =
                calculation.warnings,
        )
    }

    private fun validateReadPermission(
        travel: Travel,
        requesterId: UUID,
    ) {
        if (
            travel.owner.id ==
            requesterId
        ) {
            return
        }

        if (
            travelMemberRepository
                .findAcceptedRole(
                    travel.id,
                    requesterId,
                ) ==
            null
        ) {
            throw RouteAccessDeniedException()
        }
    }

    private fun validateDayNumber(
        travel: Travel,
        dayNumber: Int,
    ) {
        if (
            dayNumber !in
            1..travel.travelDays
        ) {
            throw InvalidRouteDayNumberException()
        }
    }

    private fun validateWaypointCount(
        waypointCount: Int,
    ) {
        if (
            waypointCount >
            MAX_ROUTE_WAYPOINTS
        ) {
            throw TooManyRouteWaypointsException()
        }
    }

    /*
     * ======================================================
     * 기존 GET 빈 경로
     * ======================================================
     */

    private fun emptyRoute(
        travelId: UUID,
        dayNumber: Int,
        transportationType: TransportationType,
    ) =
        TravelRouteResponse(
            travelId =
                travelId,

            dayNumber =
                dayNumber,

            transportationType =
                transportationType,

            encodedPolyline =
                null,

            totalDistanceMeters =
                0,

            totalDurationSeconds =
                0,

            legs =
                emptyList(),

            warnings =
                emptyList(),
        )

    /*
     * ======================================================
     * Preview 빈 경로
     * ======================================================
     */

    private fun emptyPreviewRoute(
        dayNumber: Int,
        transportationType:
            TravelRoutePreviewTransportationType,
    ) =
        TravelRoutePreviewResponse(
            dayNumber =
                dayNumber,

            transportationType =
                transportationType,

            encodedPolyline =
                null,

            encodedPolylines =
                emptyList(),

            totalDistanceMeters =
                0,

            totalDurationSeconds =
                0,

            warnings =
                emptyList(),
        )

    private data class RouteWaypoint(
        val timelineItemId: UUID,
        val googlePlaceId: String,
    )

    companion object {
        private const val MAX_ROUTE_WAYPOINTS =
            27
    }
}

class RouteTravelNotFoundException :
    DomainException(
        ErrorCode.RESOURCE_NOT_FOUND
    )

class RouteAccessDeniedException :
    DomainException(
        ErrorCode.ACCESS_DENIED
    )

class InvalidRouteDayNumberException :
    DomainException(
        ErrorCode.INVALID_REQUEST,
        "여행 일차가 올바르지 않습니다.",
    )

class InvalidRouteWaypointException :
    DomainException(
        ErrorCode.INVALID_REQUEST,
        "경로 장소 정보가 올바르지 않습니다.",
    )

class TooManyRouteWaypointsException :
    DomainException(
        ErrorCode.INVALID_REQUEST,
        "경로 지점은 출발지와 도착지를 포함해 최대 27개까지 허용됩니다.",
    )

class InvalidRouteCalculationException :
    DomainException(
        ErrorCode.GOOGLE_ROUTES_ERROR
    )