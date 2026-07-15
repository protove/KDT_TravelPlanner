package com.ktcloud.travelplanner.timeline.model

import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.math.BigDecimal
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

		assertEquals(2, item.dayNumber.toInt())
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
	fun `rejects coordinates and rating outside allowed ranges`() {
		assertThrows<IllegalArgumentException> {
			timelineItem(latitude = BigDecimal("90.000001"))
		}
		assertThrows<IllegalArgumentException> {
			timelineItem(longitude = BigDecimal("-180.000001"))
		}
		assertThrows<IllegalArgumentException> {
			timelineItem(rating = BigDecimal("5.1"))
		}
	}

	private fun timelineItem(
		dayNumber: Short = 1,
		visitDate: LocalDate = LocalDate.parse("2026-08-01"),
		category: TimelineCategory = TimelineCategory.ATTRACTION,
		foodSubcategory: String? = null,
		latitude: BigDecimal? = BigDecimal("35.658581"),
		longitude: BigDecimal? = BigDecimal("139.745433"),
		rating: BigDecimal? = BigDecimal("4.5"),
		visitOrder: Short = 1,
	): TimelineItem = TimelineItem(
		travel = travel,
		dayNumber = dayNumber,
		visitDate = visitDate,
		category = category,
		foodSubcategory = foodSubcategory,
		name = "도쿄 타워",
		latitude = latitude,
		longitude = longitude,
		rating = rating,
		visitOrder = visitOrder,
	)
}
