package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.dto.TimelineItemCreateRequest
import com.ktcloud.travelplanner.timeline.dto.TimelineItemCreateResponse
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TimelineItemService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val cityRepository: CityRepository,
	private val timelineItemRepository: TimelineItemRepository,
) {
	@Transactional
	fun createTimelineItem(
		travelId: UUID,
		requesterId: UUID,
		request: TimelineItemCreateRequest,
	): TimelineItemCreateResponse {
		val travel = travelRepository.findById(travelId).orElseThrow(::TimelineTravelNotFoundException)
		validateWritePermission(travel, requesterId)
		val dayNumber = request.dayNumber.toShort()
		val visitOrder = request.visitOrder.toShort()
		val city = request.cityId?.let { cityId ->
			cityRepository.findById(cityId).orElseThrow(::TimelineCityNotFoundException)
		}
		val timelineItem = try {
			TimelineItem(
				travel = travel,
				dayNumber = dayNumber,
				visitDate = request.visitDate,
				city = city,
				category = request.category,
				foodSubcategory = normalizeOptional(request.foodSubcategory),
				name = request.name.trim(),
				googlePlaceId = normalizeOptional(request.googlePlaceId),
				visitOrder = visitOrder,
				memo = normalizeOptional(request.memo),
			)
		} catch (_: IllegalArgumentException) {
			throw InvalidTimelineItemException()
		}
		if (timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrder(
				travelId,
				dayNumber,
				visitOrder,
			)
		) {
			throw DuplicateTimelineOrderException()
		}

		val savedItem = try {
			timelineItemRepository.saveAndFlush(timelineItem)
		} catch (_: DataIntegrityViolationException) {
			throw DuplicateTimelineOrderException()
		}
		return TimelineItemCreateResponse.from(savedItem)
	}

	private fun validateWritePermission(
		travel: Travel,
		requesterId: UUID,
	) {
		if (travel.owner.id == requesterId) {
			return
		}
		if (!travelMemberRepository.existsAcceptedReadWriteMember(travel.id, requesterId)) {
			throw TimelineWriteAccessDeniedException()
		}
	}

	private fun normalizeOptional(value: String?): String? = value?.trim()?.takeIf(String::isNotEmpty)
}

class TimelineTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineCityNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineWriteAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidTimelineItemException : DomainException(ErrorCode.INVALID_REQUEST, "타임라인 항목이 올바르지 않습니다.")

class DuplicateTimelineOrderException : DomainException(ErrorCode.CONFLICT, "같은 일차에 방문 순서가 중복됩니다.")
