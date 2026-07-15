package com.ktcloud.travelplanner.timeline.repository

import com.ktcloud.travelplanner.timeline.model.TimelineItem
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface TimelineItemRepository : JpaRepository<TimelineItem, UUID> {
	fun existsByTravelIdAndDayNumberAndVisitOrder(
		travelId: UUID,
		dayNumber: Short,
		visitOrder: Short,
	): Boolean
}
