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
import java.math.BigDecimal
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

        // null이면 "미배정" 상태 (아직 날짜를 정하지 않은 후보 목적지)
        dayNumber: Short?,
        visitDate: LocalDate?,

        @ManyToOne(fetch = FetchType.LAZY)
        @JoinColumn(name = "city_id")
        var city: City? = null,

        category: TimelineCategory,
        foodSubcategory: String? = null,
        name: String,
        googlePlaceId: String? = null,
        latitude: BigDecimal? = null,
        longitude: BigDecimal? = null,
        rating: BigDecimal? = null,
        visitOrder: Short,
        memo: String? = null,
) {
        @Column(name = "day_number")
        var dayNumber: Short? = dayNumber
                protected set

        @Column(name = "visit_date")
        var visitDate: LocalDate? = visitDate
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

        @Column(name = "google_place_id", length = 255)
        var googlePlaceId: String? = googlePlaceId
                protected set

        @Column(precision = 9, scale = 6)
        var latitude: BigDecimal? = latitude
                protected set

        @Column(precision = 10, scale = 6)
        var longitude: BigDecimal? = longitude
                protected set

        @Column(precision = 2, scale = 1)
        var rating: BigDecimal? = rating
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
                        googlePlaceId,
                        latitude,
                        longitude,
                        rating,
                        visitOrder,
                )
        }

        fun updateDetails(
                dayNumber: Short?,
                visitDate: LocalDate?,
                city: City?,
                category: TimelineCategory,
                foodSubcategory: String?,
                name: String,
                googlePlaceId: String?,
                latitude: BigDecimal?,
                longitude: BigDecimal?,
                rating: BigDecimal?,
                visitOrder: Short,
                memo: String?,
        ) {
                validateDetails(
                        dayNumber,
                        visitDate,
                        category,
                        foodSubcategory,
                        name,
                        googlePlaceId,
                        latitude,
                        longitude,
                        rating,
                        visitOrder,
                )
                this.dayNumber = dayNumber
                this.visitDate = visitDate
                this.city = city
                this.categoryValue = category.toApiValue()
                this.foodSubcategory = foodSubcategory
                this.name = name
                this.googlePlaceId = googlePlaceId
                this.latitude = latitude
                this.longitude = longitude
                this.rating = rating
                this.visitOrder = visitOrder
                this.memo = memo
        }

        // 미배정 상태의 목적지를 특정 날짜로 배정할 때 사용
        fun assignToDay(
                dayNumber: Short,
                visitDate: LocalDate,
        ) {
                validateDayAndDate(dayNumber, visitDate)
                this.dayNumber = dayNumber
                this.visitDate = visitDate
        }

        // 배정된 목적지를 다시 미배정 상태로 되돌릴 때 사용
        fun unassign() {
                this.dayNumber = null
                this.visitDate = null
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
                dayNumber: Short?,
                visitDate: LocalDate?,
                category: TimelineCategory,
                foodSubcategory: String?,
                name: String,
                googlePlaceId: String?,
                latitude: BigDecimal?,
                longitude: BigDecimal?,
                rating: BigDecimal?,
                visitOrder: Short,
        ) {
                // dayNumber와 visitDate는 둘 다 있거나 둘 다 없어야 함 (미배정 상태 표현)
                require((dayNumber == null) == (visitDate == null)) {
                        "dayNumber and visitDate must be both null or both present."
                }
                if (dayNumber != null && visitDate != null) {
                        validateDayAndDate(dayNumber, visitDate)
                }
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
                require(googlePlaceId == null || googlePlaceId.length <= GOOGLE_PLACE_ID_MAX_LENGTH) {
                        "googlePlaceId must not exceed $GOOGLE_PLACE_ID_MAX_LENGTH characters."
                }
                require(latitude == null || latitude in MIN_LATITUDE..MAX_LATITUDE) {
                        "latitude must be between -90 and 90."
                }
                require(longitude == null || longitude in MIN_LONGITUDE..MAX_LONGITUDE) {
                        "longitude must be between -180 and 180."
                }
                require(rating == null || rating in MIN_RATING..MAX_RATING) {
                        "rating must be between 0 and 5."
                }
        }

        // dayNumber/visitDate가 둘 다 값이 있을 때만 호출되는 교차 검증
        private fun validateDayAndDate(
                dayNumber: Short,
                visitDate: LocalDate,
        ) {
                require(dayNumber > 0) { "dayNumber must be positive." }
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
                private const val GOOGLE_PLACE_ID_MAX_LENGTH = 255
                private val MIN_LATITUDE = BigDecimal("-90")
                private val MAX_LATITUDE = BigDecimal("90")
                private val MIN_LONGITUDE = BigDecimal("-180")
                private val MAX_LONGITUDE = BigDecimal("180")
                private val MIN_RATING = BigDecimal.ZERO
                private val MAX_RATING = BigDecimal("5")
        }
}
