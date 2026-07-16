package com.ktcloud.travelplanner.timeline.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.timeline.dto.TimelineItemCreateRequest
import com.ktcloud.travelplanner.timeline.dto.TimelineItemCreateResponse
import com.ktcloud.travelplanner.timeline.dto.TimelineItemResponse
import com.ktcloud.travelplanner.timeline.dto.TimelineItemUpdateRequest
import com.ktcloud.travelplanner.timeline.service.TimelineItemService
import com.ktcloud.travelplanner.timeline.service.TimelineItemUpdateService
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travels/{travelId}/timeline-items")
class TimelineItemController(
	private val timelineItemService: TimelineItemService,
	private val timelineItemUpdateService: TimelineItemUpdateService,
) {
	@PostMapping
	fun createTimelineItem(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@Valid @RequestBody request: TimelineItemCreateRequest,
	): ApiResponse<TimelineItemCreateResponse> =
		ApiResponse.success(timelineItemService.createTimelineItem(travelId, principal.userId, request))

	@PatchMapping("/{itemId}")
	fun updateTimelineItem(
		@PathVariable travelId: UUID,
		@PathVariable itemId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestBody request: TimelineItemUpdateRequest,
	): ApiResponse<TimelineItemResponse> = ApiResponse.success(
		timelineItemUpdateService.updateTimelineItem(travelId, itemId, principal.userId, request),
	)
}
