package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.place.dto.TravelMapPointResponse
import com.ktcloud.travelplanner.place.dto.TravelMapPointsResponse
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TravelMapPointService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val timelineItemRepository: TimelineItemRepository,
        private val placeLocationService: PlaceLocationService,
) {
        @Transactional(readOnly = true)
        fun getMapPoints(
                travelId: UUID,
                requesterId: UUID,
                dayNumber: Int,
        ): TravelMapPointsResponse {
                val travel = travelRepository.findById(travelId)
                        .orElseThrow(::MapPointTravelNotFoundException)

                validateReadPermission(travel, requesterId)

                if (dayNumber !in 1..travel.travelDays) {
                        throw InvalidMapDayNumberException()
                }

                val points = mutableListOf<TravelMapPointResponse>()
                val unmappedTimelineItemIds = mutableListOf<UUID>()
                val unresolvedTimelineItemIds = mutableListOf<UUID>()

                val timelineItems = timelineItemRepository
                        .findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(travelId)
                        .filter { timelineItem ->
                                timelineItem.dayNumber == dayNumber.toShort() ||
                                        timelineItem.dayNumber == null
                        }

                timelineItems.forEach { timelineItem ->
                        val googlePlaceId = timelineItem.googlePlaceId
                                ?.takeIf { it.isNotBlank() }

                        if (googlePlaceId == null) {
                                unmappedTimelineItemIds += timelineItem.id
                                return@forEach
                        }

                        val location = placeLocationService.getLocation(googlePlaceId)

                        if (location == null) {
                                unresolvedTimelineItemIds += timelineItem.id
                                return@forEach
                        }

                        points += TravelMapPointResponse.from(
                                timelineItem,
                                location,
                        )
                }

                return TravelMapPointsResponse(
                        travelId = travelId,
                        dayNumber = dayNumber,
                        points = points,
                        unmappedTimelineItemIds = unmappedTimelineItemIds,
                        unresolvedTimelineItemIds = unresolvedTimelineItemIds,
                )
        }

        private fun validateReadPermission(
                travel: Travel,
                requesterId: UUID,
        ) {
                if (travel.owner.id == requesterId) {
                        return
                }

                if (travelMemberRepository.findAcceptedRole(travel.id, requesterId) == null) {
                        throw MapPointAccessDeniedException()
                }
        }
}

class MapPointTravelNotFoundException :
        DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class MapPointAccessDeniedException :
        DomainException(ErrorCode.ACCESS_DENIED)

class InvalidMapDayNumberException :
        DomainException(
                ErrorCode.INVALID_REQUEST,
                "여행 일차가 올바르지 않습니다.",
        )