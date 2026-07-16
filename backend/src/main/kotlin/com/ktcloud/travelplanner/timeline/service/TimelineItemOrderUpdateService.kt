package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdateRequest
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TimelineItemOrderUpdateService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val timelineItemRepository: TimelineItemRepository,
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
		val timelineItems = timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(
			travelId,
			dayNumber,
		)
		validatePermutation(timelineItems, request)
		reorder(timelineItems, request)
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
		timelineItems: List<TimelineItem>,
		request: TimelineItemOrderUpdateRequest,
	) {
		val itemCount = timelineItems.size
		val existingItemIds = timelineItems.map(TimelineItem::id).toSet()
		val requestedItemIds = request.items.map { it.itemId }
		val requestedVisitOrders = request.items.map { it.visitOrder }
		val expectedVisitOrders = (1..itemCount).toSet()

		if (itemCount == 0 ||
			requestedItemIds.size != itemCount ||
			requestedItemIds.toSet().size != itemCount ||
			requestedItemIds.toSet() != existingItemIds ||
			requestedVisitOrders.toSet().size != itemCount ||
			requestedVisitOrders.toSet() != expectedVisitOrders ||
			timelineItems.map { it.visitOrder.toInt() }.toSet() != expectedVisitOrders ||
			itemCount >= Short.MAX_VALUE.toInt()
		) {
			throw InvalidTimelineItemOrderException()
		}
	}

	private fun reorder(
		timelineItems: List<TimelineItem>,
		request: TimelineItemOrderUpdateRequest,
	) {
		val timelineItemsById = timelineItems.associateBy(TimelineItem::id)
		val timelineItemsByOrder = timelineItems.associateBy { it.visitOrder.toInt() }.toMutableMap()
		val requestedItemIdsByOrder = request.items.associate { it.visitOrder to it.itemId }
		val temporaryVisitOrder = (timelineItems.size + 1).toShort()

		for (desiredVisitOrder in 1..timelineItems.size) {
			val targetItem = timelineItemsById.getValue(requestedItemIdsByOrder.getValue(desiredVisitOrder))
			val currentVisitOrder = targetItem.visitOrder.toInt()
			if (currentVisitOrder == desiredVisitOrder) continue

			val displacedItem = timelineItemsByOrder.getValue(desiredVisitOrder)
			persistVisitOrder(displacedItem, temporaryVisitOrder)
			timelineItemsByOrder.remove(desiredVisitOrder)
			timelineItemsByOrder[temporaryVisitOrder.toInt()] = displacedItem

			persistVisitOrder(targetItem, desiredVisitOrder.toShort())
			timelineItemsByOrder.remove(currentVisitOrder)
			timelineItemsByOrder[desiredVisitOrder] = targetItem

			persistVisitOrder(displacedItem, currentVisitOrder.toShort())
			timelineItemsByOrder.remove(temporaryVisitOrder.toInt())
			timelineItemsByOrder[currentVisitOrder] = displacedItem
		}
	}

	private fun persistVisitOrder(
		timelineItem: TimelineItem,
		visitOrder: Short,
	) {
		timelineItem.changeVisitOrder(visitOrder)
		timelineItemRepository.saveAndFlush(timelineItem)
	}

	private fun Int.toShortChecked(): Short {
		if (this !in 1..Short.MAX_VALUE.toInt()) throw InvalidTimelineItemOrderException()
		return toShort()
	}
}

class TimelineOrderTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineItemOrderUpdateAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidTimelineItemOrderException : DomainException(
	ErrorCode.INVALID_REQUEST,
	"타임라인 방문 순서가 올바르지 않습니다.",
)
