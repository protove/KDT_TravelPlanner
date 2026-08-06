package com.ktcloud.travelplanner.timeline.repository

import com.ktcloud.travelplanner.timeline.model.TimelineItem
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface TimelineItemRepository : JpaRepository<TimelineItem, UUID> {
	fun existsByTravelIdAndDayNumberAndVisitOrder(
		travelId: UUID,
		dayNumber: Short,
		visitOrder: Short,
	): Boolean

	fun findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(travelId: UUID): List<TimelineItem>

	fun findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(
		travelId: UUID,
		dayNumber: Short,
	): List<TimelineItem>

	fun findByIdAndTravelId(
		itemId: UUID,
		travelId: UUID,
	): TimelineItem?

	fun existsByTravelIdAndDayNumberAndVisitOrderAndIdNot(
		travelId: UUID,
		dayNumber: Short,
		visitOrder: Short,
		itemId: UUID,
	): Boolean

	@Query(
		"""
		SELECT timelineItem
		FROM TimelineItem timelineItem
		WHERE timelineItem.travel.id = :travelId
		  AND timelineItem.dayNumber = :dayNumber
		  AND timelineItem.visitOrder > :visitOrder
		ORDER BY timelineItem.visitOrder ASC
		""",
	)
	fun findItemsAfterVisitOrder(
		@Param("travelId") travelId: UUID,
		@Param("dayNumber") dayNumber: Short,
		@Param("visitOrder") visitOrder: Short,
	): List<TimelineItem>
}
