package com.ktcloud.travelplanner.travel.repository

import com.ktcloud.travelplanner.membership.model.TravelRole
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

data class TravelListRow(
	val travelId: UUID,
	val title: String,
	val startDate: LocalDate,
	val endDate: LocalDate,
	val countryId: Short?,
	val cityId: Long?,
	val participantCount: Short?,
	val updatedAt: Instant,
	val memberRole: TravelRole?,
)
