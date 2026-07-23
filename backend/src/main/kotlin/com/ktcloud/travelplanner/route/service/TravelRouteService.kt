package com.ktcloud.travelplanner.route.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.route.dto.TravelRouteLegResponse
import com.ktcloud.travelplanner.route.dto.TravelRouteResponse
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
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
	@Transactional(readOnly = true)
	fun getRoute(
		travelId: UUID,
		requesterId: UUID,
		dayNumber: Int,
		transportationType: TransportationType,
	): TravelRouteResponse {
		val travel = travelRepository.findById(travelId).orElseThrow(::RouteTravelNotFoundException)
		validateReadPermission(travel, requesterId)
		if (dayNumber !in 1..travel.travelDays) throw InvalidRouteDayNumberException()

		val waypoints = timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(
			travelId,
			dayNumber.toShort(),
		).mapNotNull { timelineItem ->
			timelineItem.googlePlaceId?.takeIf(String::isNotBlank)?.let { placeId ->
				RouteWaypoint(timelineItem.id, placeId)
			}
		}
		if (waypoints.size > MAX_ROUTE_WAYPOINTS) throw TooManyRouteWaypointsException()
		if (waypoints.size <= 1) return emptyRoute(travelId, dayNumber, transportationType)

		val calculation = routeCalculationPort.calculateRoute(
			waypoints.map { it.googlePlaceId },
			transportationType,
		)
		if (calculation.legs.size != waypoints.size - 1) throw InvalidRouteCalculationException()
		val legs = calculation.legs.mapIndexed { index, leg ->
			TravelRouteLegResponse(
				fromTimelineItemId = waypoints[index].timelineItemId,
				toTimelineItemId = waypoints[index + 1].timelineItemId,
				distanceMeters = leg.distanceMeters,
				durationSeconds = leg.durationSeconds,
			)
		}
		return TravelRouteResponse(
			travelId = travelId,
			dayNumber = dayNumber,
			transportationType = transportationType,
			encodedPolyline = calculation.encodedPolyline,
			totalDistanceMeters = calculation.totalDistanceMeters,
			totalDurationSeconds = calculation.totalDurationSeconds,
			legs = legs,
			warnings = calculation.warnings,
		)
	}

	private fun validateReadPermission(travel: Travel, requesterId: UUID) {
		if (travel.owner.id == requesterId) return
		if (travelMemberRepository.findAcceptedRole(travel.id, requesterId) == null) {
			throw RouteAccessDeniedException()
		}
	}

	private fun emptyRoute(
		travelId: UUID,
		dayNumber: Int,
		transportationType: TransportationType,
	) = TravelRouteResponse(
		travelId = travelId,
		dayNumber = dayNumber,
		transportationType = transportationType,
		encodedPolyline = null,
		totalDistanceMeters = 0,
		totalDurationSeconds = 0,
		legs = emptyList(),
		warnings = emptyList(),
	)

	private data class RouteWaypoint(
		val timelineItemId: UUID,
		val googlePlaceId: String,
	)

	companion object {
		private const val MAX_ROUTE_WAYPOINTS = 27
	}
}

class RouteTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class RouteAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidRouteDayNumberException : DomainException(ErrorCode.INVALID_REQUEST, "여행 일차가 올바르지 않습니다.")

class TooManyRouteWaypointsException : DomainException(
	ErrorCode.INVALID_REQUEST,
	"경로 지점은 출발지와 도착지를 포함해 최대 27개까지 허용됩니다.",
)

class InvalidRouteCalculationException : DomainException(ErrorCode.GOOGLE_ROUTES_ERROR)
