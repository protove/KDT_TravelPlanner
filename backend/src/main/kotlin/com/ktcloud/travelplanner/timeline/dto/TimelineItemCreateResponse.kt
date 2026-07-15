package com.ktcloud.travelplanner.timeline.dto

import com.ktcloud.travelplanner.timeline.model.TimelineItem
import java.util.UUID

data class TimelineItemCreateResponse(
	val timelineItemId: UUID,
) {
	companion object {
		fun from(timelineItem: TimelineItem): TimelineItemCreateResponse =
			TimelineItemCreateResponse(timelineItem.id)
	}
}
