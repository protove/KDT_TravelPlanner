package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.membership.dto.ReceivedTravelInvitationResponse
import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.service.TravelInvitationService
import jakarta.validation.constraints.Max
import jakarta.validation.constraints.Min
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.validation.annotation.Validated
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@Validated
@RestController
@RequestMapping("/api/v1/users/me/travel-invitations")
class ReceivedTravelInvitationController(
	private val travelInvitationService: TravelInvitationService,
) {
	@GetMapping
	fun getReceivedInvitations(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestParam(defaultValue = "PENDING") status: InvitationStatus,
		@RequestParam(defaultValue = "0") @Min(0) page: Int,
		@RequestParam(defaultValue = "20") @Min(1) @Max(100) size: Int,
	): ApiResponse<PageResponse<ReceivedTravelInvitationResponse>> =
		ApiResponse.success(
			travelInvitationService.getReceivedInvitations(principal.userId, status, page, size),
		)
}
