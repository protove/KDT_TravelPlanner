package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.membership.dto.TravelInvitationRespondRequest
import com.ktcloud.travelplanner.membership.dto.TravelInvitationStatusResponse
import com.ktcloud.travelplanner.membership.service.TravelInvitationService
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travel-invitations")
class TravelInvitationResponseController(
	private val travelInvitationService: TravelInvitationService,
) {
	@PatchMapping("/{invitationId}")
	fun respondToInvitation(
		@PathVariable invitationId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestBody request: TravelInvitationRespondRequest,
	): ApiResponse<TravelInvitationStatusResponse> =
		ApiResponse.success(
			travelInvitationService.respondToInvitation(invitationId, principal.userId, request),
		)
}
