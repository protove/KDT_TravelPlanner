package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdate
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdateRequest
import com.ktcloud.travelplanner.timeline.repository.TimelineItemOrderRepository
import com.ktcloud.travelplanner.timeline.repository.TimelineItemOrderSnapshot
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TimelineItemOrderUpdateService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val timelineItemOrderRepository: TimelineItemOrderRepository,
) {
	@Transactional
	fun updateTimelineItemOrder(
		travelId: UUID,
		requesterId: UUID,
		request: TimelineItemOrderUpdateRequest,
	) {
		val travel = travelRepository.findById(travelId).orElseThrow(::TimelineOrderTravelNotFoundException)
		if (travel.isDeleted) throw TimelineOrderTravelNotFoundException()
		validateWritePermission(travel, requesterId)
		val dayNumber = request.dayNumber.toShortChecked()
		val timelineItemOrderSnapshots = timelineItemOrderRepository.findLockedByTravelIdAndDayNumber(
			travelId,
			dayNumber,
		)
		validatePermutation(timelineItemOrderSnapshots, request)
		val requestedItems = request.items.sortedBy(TimelineItemOrderUpdate::visitOrder)
		if (timelineItemOrderSnapshots.isNoop(requestedItems)) return
		timelineItemOrderRepository.updateVisitOrders(
			travelId = travelId,
			dayNumber = dayNumber,
			itemIds = requestedItems.map(TimelineItemOrderUpdate::itemId),
			visitOrders = requestedItems.map { it.visitOrder.toShort() },
		)
	}

	private fun validateWritePermission(
		travel: Travel,
		requesterId: UUID,
	) {
		if (travel.owner.id == requesterId) return
		if (!travelMemberRepository.existsAcceptedReadWriteMember(travel.id, requesterId)) {
			throw TimelineItemOrderUpdateAccessDeniedException()
		}
	}

	private fun validatePermutation(
		timelineItemOrderSnapshots: List<TimelineItemOrderSnapshot>,
		request: TimelineItemOrderUpdateRequest,
	) {
		val itemCount = timelineItemOrderSnapshots.size
		val existingItemIds = timelineItemOrderSnapshots.map(TimelineItemOrderSnapshot::itemId).toSet()
		val requestedItemIds = request.items.map { it.itemId }
		val requestedVisitOrders = request.items.map { it.visitOrder }
		val expectedVisitOrders = (1..itemCount).toSet()

		if (itemCount == 0 ||
			requestedItemIds.size != itemCount ||
			requestedItemIds.toSet().size != itemCount ||
			requestedItemIds.toSet() != existingItemIds ||
			requestedVisitOrders.toSet().size != itemCount ||
			requestedVisitOrders.toSet() != expectedVisitOrders ||
			timelineItemOrderSnapshots.map { it.visitOrder.toInt() }.toSet() != expectedVisitOrders
		) {
			throw InvalidTimelineItemOrderException()
		}
	}

	private fun Int.toShortChecked(): Short {
		if (this !in 1..Short.MAX_VALUE.toInt()) throw InvalidTimelineItemOrderException()
		return toShort()
	}

	private fun List<TimelineItemOrderSnapshot>.isNoop(
		requestedItems: List<TimelineItemOrderUpdate>,
	): Boolean {
		val requestedVisitOrdersByItemId = requestedItems.associate { it.itemId to it.visitOrder }
		return all { snapshot -> requestedVisitOrdersByItemId.getValue(snapshot.itemId) == snapshot.visitOrder.toInt() }
	}
}

class TimelineOrderTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineItemOrderUpdateAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidTimelineItemOrderException : DomainException(
	ErrorCode.INVALID_REQUEST,
	"타임라인 방문 순서가 올바르지 않습니다.",
)
