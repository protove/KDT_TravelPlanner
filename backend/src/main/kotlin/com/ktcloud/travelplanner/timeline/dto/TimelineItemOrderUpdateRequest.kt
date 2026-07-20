package com.ktcloud.travelplanner.timeline.dto

import jakarta.validation.Valid
import jakarta.validation.constraints.Min
import jakarta.validation.constraints.NotEmpty
import java.util.UUID

data class TimelineItemOrderUpdateRequest(
	@field:Min(1)
	val dayNumber: Int,

	@field:NotEmpty
	@field:Valid
	val items: List<TimelineItemOrderUpdate>,
)

data class TimelineItemOrderUpdate(
	val itemId: UUID,

	@field:Min(1)
	val visitOrder: Int,
)
