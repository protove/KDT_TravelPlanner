package com.ktcloud.travelplanner.travel.dto

import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.travel.repository.TravelListRow
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

data class TravelSummaryResponse(
	val travelId: UUID,
	val title: String,
	val startDate: LocalDate,
	val endDate: LocalDate,
	val countryId: Short?,
	val cityId: Long?,
	val participantCount: Int?,
	val permission: TravelPermission,
	val updatedAt: Instant,
) {
	companion object {
		fun from(row: TravelListRow): TravelSummaryResponse = TravelSummaryResponse(
			travelId = row.travelId,
			title = row.title,
			startDate = row.startDate,
			endDate = row.endDate,
			countryId = row.countryId,
			cityId = row.cityId,
			participantCount = row.participantCount?.toInt(),
			permission = row.memberRole?.let { TravelPermission.valueOf(it.name) } ?: TravelPermission.OWNER,
			updatedAt = row.updatedAt,
		)
	}
}
