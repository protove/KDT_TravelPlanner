package com.ktcloud.travelplanner.timeline.dto
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import java.math.BigDecimal
import java.time.LocalDate
import java.util.UUID
data class TimelineItemResponse(
        val timelineItemId: UUID,
        val dayNumber: Int?,
        val visitDate: LocalDate?,
        val cityId: Long?,
        val category: TimelineCategory,
        val foodSubcategory: String?,
        val name: String,
        val googlePlaceId: String?,
        val latitude: BigDecimal?,
        val longitude: BigDecimal?,
        val rating: BigDecimal?,
        val visitOrder: Int,
        val memo: String?,
) {
        companion object {
                fun from(timelineItem: TimelineItem): TimelineItemResponse = TimelineItemResponse(
                        timelineItemId = timelineItem.id,
                        dayNumber = timelineItem.dayNumber?.toInt(),
                        visitDate = timelineItem.visitDate,
                        cityId = timelineItem.city?.id,
                        category = timelineItem.category,
                        foodSubcategory = timelineItem.foodSubcategory,
                        name = timelineItem.name,
                        googlePlaceId = timelineItem.googlePlaceId,
                        latitude = timelineItem.latitude,
                        longitude = timelineItem.longitude,
                        rating = timelineItem.rating,
                        visitOrder = timelineItem.visitOrder.toInt(),
                        memo = timelineItem.memo,
                )
        }
}
