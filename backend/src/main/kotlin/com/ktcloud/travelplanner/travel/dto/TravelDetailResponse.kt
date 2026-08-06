package com.ktcloud.travelplanner.travel.dto

import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.timeline.dto.TimelineItemResponse
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.travel.model.CompanionType
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.model.TravelPurpose
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

data class TravelDetailResponse(
        val travelId: UUID,
        val ownerId: UUID,
        val title: String,
        val startDate: LocalDate,
        val endDate: LocalDate,
        val travelDays: Int,
        val countryId: Short?,
        val cityId: Long?,
        val companionType: CompanionType?,
        val participantCount: Int?,
        val comment: String?,
        val purposes: Set<TravelPurpose>,
        val version: Long,
        val permission: TravelPermission,
        val createdAt: Instant,
        val updatedAt: Instant,
        val timelineItems: List<TimelineItemResponse>,
) {
        companion object {
                fun from(
                        travel: Travel,
                        permission: TravelPermission,
                        timelineItems: List<TimelineItem>,
                        purposes: Set<TravelPurpose>,
                ): TravelDetailResponse = TravelDetailResponse(
                        travelId = travel.id,
                        ownerId = requireNotNull(travel.owner.id),
                        title = travel.title,
                        startDate = travel.startDate,
                        endDate = travel.endDate,
                        travelDays = travel.travelDays,
                        countryId = travel.country?.id,
                        cityId = travel.city?.id,
                        companionType = travel.companionType,
                        participantCount = travel.participantCount?.toInt(),
                        comment = travel.comment,
                        purposes = purposes,
                        version = travel.version,
                        permission = permission,
                        createdAt = travel.createdAt,
                        updatedAt = travel.updatedAt,
                        timelineItems = timelineItems.map(TimelineItemResponse::from),
                )
        }
}
