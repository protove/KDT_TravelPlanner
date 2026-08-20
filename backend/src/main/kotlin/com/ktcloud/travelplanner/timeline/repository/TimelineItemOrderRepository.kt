package com.ktcloud.travelplanner.timeline.repository

import java.util.UUID

data class TimelineItemOrderSnapshot(
	val itemId: UUID,
	val visitOrder: Short,
)

interface TimelineItemOrderRepository {
	fun findLockedByTravelIdAndDayNumber(
		travelId: UUID,
		dayNumber: Short,
	): List<TimelineItemOrderSnapshot>

	fun updateVisitOrders(
		travelId: UUID,
		dayNumber: Short,
		itemIds: List<UUID>,
		visitOrders: List<Short>,
	)
}
