package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateRequest
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateResponse
import com.ktcloud.travelplanner.membership.service.TravelInvitationService
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travels/{travelId}/invitations")
class TravelInvitationController(
	private val travelInvitationService: TravelInvitationService,
) {
	@PostMapping
	fun createInvitation(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@Valid @RequestBody request: TravelInvitationCreateRequest,
	): ApiResponse<TravelInvitationCreateResponse> =
		ApiResponse.success(
			travelInvitationService.createInvitation(travelId, principal.userId, request),
		)
}
