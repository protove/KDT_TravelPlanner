package com.ktcloud.travelplanner.timeline.model

import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.travel.model.Travel
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.UUID

@Entity
@Table(name = "timeline_table")
class TimelineItem(
	@Id
	val id: UUID = UUID.randomUUID(),

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "planner_id", nullable = false)
	val travel: Travel,

	dayNumber: Short,
	visitDate: LocalDate,

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "city_id")
	var city: City? = null,

	category: TimelineCategory,
	foodSubcategory: String? = null,
	name: String,
	googlePlaceId: String? = null,
	visitOrder: Short,
	memo: String? = null,
) {
	@Column(name = "day_number", nullable = false)
	var dayNumber: Short = dayNumber
		protected set

	@Column(name = "visit_date", nullable = false)
	var visitDate: LocalDate = visitDate
		protected set

	@Column(name = "category", nullable = false, length = 20)
	private var categoryValue: String = category.toApiValue()

	val category: TimelineCategory
		get() = TimelineCategory.fromApiValue(categoryValue)

	@Column(name = "food_subcategory", length = 30)
	var foodSubcategory: String? = foodSubcategory
		protected set

	@Column(nullable = false, length = 100)
	var name: String = name
		protected set

	@Column(name = "google_place_id", columnDefinition = "TEXT")
	var googlePlaceId: String? = googlePlaceId
		protected set

	@Column(name = "visit_order", nullable = false)
	var visitOrder: Short = visitOrder
		protected set

	@Column(columnDefinition = "TEXT")
	var memo: String? = memo
		protected set

	init {
		validateDetails(
			dayNumber,
			visitDate,
			category,
			foodSubcategory,
			name,
			visitOrder,
		)
	}

	fun updateDetails(
		dayNumber: Short,
		visitDate: LocalDate,
		city: City?,
		category: TimelineCategory,
		foodSubcategory: String?,
		name: String,
		googlePlaceId: String?,
		visitOrder: Short,
		memo: String?,
	) {
		validateDetails(
			dayNumber,
			visitDate,
			category,
			foodSubcategory,
			name,
			visitOrder,
		)
		this.dayNumber = dayNumber
		this.visitDate = visitDate
		this.city = city
		this.categoryValue = category.toApiValue()
		this.foodSubcategory = foodSubcategory
		this.name = name
		this.googlePlaceId = googlePlaceId
		this.visitOrder = visitOrder
		this.memo = memo
	}

	fun moveVisitOrderEarlier() {
		require(visitOrder > 1) { "visitOrder must remain positive." }
		visitOrder--
	}

	fun changeVisitOrder(newVisitOrder: Short) {
		require(newVisitOrder > 0) { "visitOrder must be positive." }
		visitOrder = newVisitOrder
	}

	private fun validateDetails(
		dayNumber: Short,
		visitDate: LocalDate,
		category: TimelineCategory,
		foodSubcategory: String?,
		name: String,
		visitOrder: Short,
	) {
		require(dayNumber > 0) { "dayNumber must be positive." }
		require(visitOrder > 0) { "visitOrder must be positive." }
		require(name.isNotBlank()) { "name must not be blank." }
		require(name.length <= NAME_MAX_LENGTH) { "name must not exceed $NAME_MAX_LENGTH characters." }
		require(foodSubcategory == null || foodSubcategory.isNotBlank()) {
			"foodSubcategory must not be blank."
		}
		require(foodSubcategory == null || foodSubcategory.length <= FOOD_SUBCATEGORY_MAX_LENGTH) {
			"foodSubcategory must not exceed $FOOD_SUBCATEGORY_MAX_LENGTH characters."
		}
		require(foodSubcategory == null || category == TimelineCategory.FOOD) {
			"foodSubcategory is allowed only for food category."
		}
		require(!visitDate.isBefore(travel.startDate) && !visitDate.isAfter(travel.endDate)) {
			"visitDate must be within the travel period."
		}
		val expectedDayNumber = ChronoUnit.DAYS.between(travel.startDate, visitDate) + 1
		require(dayNumber.toLong() == expectedDayNumber) {
			"dayNumber must match visitDate."
		}
	}

	companion object {
		private const val NAME_MAX_LENGTH = 100
		private const val FOOD_SUBCATEGORY_MAX_LENGTH = 30
	}
}
