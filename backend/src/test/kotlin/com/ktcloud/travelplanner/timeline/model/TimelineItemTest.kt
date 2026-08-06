package com.ktcloud.travelplanner.timeline.model

import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.LocalDate
import kotlin.test.assertEquals

class TimelineItemTest {
	private val travel = Travel(
		owner = User(OAuthProvider.GOOGLE, "timeline-owner"),
		title = "타임라인 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	@Test
	fun `accepts matching day number and visit date`() {
		val item = timelineItem(
			dayNumber = 2,
			visitDate = LocalDate.parse("2026-08-02"),
			category = TimelineCategory.FOOD,
			foodSubcategory = "일식",
		)

		assertEquals(2, item.dayNumber?.toInt())
		assertEquals(LocalDate.parse("2026-08-02"), item.visitDate)
		assertEquals(TimelineCategory.FOOD, item.category)
	}

	@Test
	fun `rejects mismatched day number date and non positive order`() {
		assertThrows<IllegalArgumentException> {
			timelineItem(dayNumber = 1, visitDate = LocalDate.parse("2026-08-02"))
		}
		assertThrows<IllegalArgumentException> {
			timelineItem(dayNumber = 4, visitDate = LocalDate.parse("2026-08-04"))
		}
		assertThrows<IllegalArgumentException> {
			timelineItem(visitOrder = 0)
		}
	}

	@Test
	fun `allows food subcategory only for food category`() {
		assertThrows<IllegalArgumentException> {
			timelineItem(category = TimelineCategory.ATTRACTION, foodSubcategory = "일식")
		}
		assertThrows<IllegalArgumentException> {
			timelineItem(category = TimelineCategory.FOOD, foodSubcategory = " ")
		}
		timelineItem(category = TimelineCategory.FOOD, foodSubcategory = "일식")
	}

	@Test
	fun `accepts nullable and long Google Place IDs`() {
		val longPlaceId = "place".repeat(100)

		assertEquals(longPlaceId, timelineItem(googlePlaceId = longPlaceId).googlePlaceId)
		assertEquals(null, timelineItem(googlePlaceId = null).googlePlaceId)
	}

	@Test
	fun `partial update target values are revalidated`() {
		val item = timelineItem(category = TimelineCategory.FOOD, foodSubcategory = "일식")

		item.updateDetails(
			dayNumber = 2,
			visitDate = LocalDate.parse("2026-08-02"),
			city = null,
			category = TimelineCategory.OTHER,
			foodSubcategory = null,
			name = "수정 일정",
			googlePlaceId = null,
			visitOrder = 2,
			memo = null,
		)

		assertEquals(2, item.dayNumber?.toInt())
		assertEquals(TimelineCategory.OTHER, item.category)
		assertEquals("수정 일정", item.name)
		assertThrows<IllegalArgumentException> {
			item.updateDetails(
				item.dayNumber,
				item.visitDate,
				null,
				TimelineCategory.ATTRACTION,
				"일식",
				item.name,
				null,
				item.visitOrder,
				null,
			)
		}
	}

	@Test
	fun `moves visit order one position earlier without becoming non positive`() {
		val item = timelineItem(visitOrder = 2)

		item.moveVisitOrderEarlier()

		assertEquals(1, item.visitOrder.toInt())
		assertThrows<IllegalArgumentException> { item.moveVisitOrderEarlier() }
	}

	@Test
	fun `changes visit order only to a positive value`() {
		val item = timelineItem(visitOrder = 1)

		item.changeVisitOrder(3)

		assertEquals(3, item.visitOrder.toInt())
		assertThrows<IllegalArgumentException> { item.changeVisitOrder(0) }
	}

	private fun timelineItem(
		dayNumber: Short = 1,
		visitDate: LocalDate = LocalDate.parse("2026-08-01"),
		category: TimelineCategory = TimelineCategory.ATTRACTION,
		foodSubcategory: String? = null,
		googlePlaceId: String? = "google-place-id",
		visitOrder: Short = 1,
	): TimelineItem = TimelineItem(
		travel = travel,
		dayNumber = dayNumber,
		visitDate = visitDate,
		category = category,
		foodSubcategory = foodSubcategory,
		name = "도쿄 타워",
		googlePlaceId = googlePlaceId,
		visitOrder = visitOrder,
	)
}
