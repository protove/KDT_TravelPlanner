package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.membership.dto.TravelMemberResponse
import com.ktcloud.travelplanner.membership.service.TravelMemberQueryService
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travels/{travelId}/members")
class TravelMemberController(
	private val travelMemberQueryService: TravelMemberQueryService,
) {
	@GetMapping
	fun getTravelMembers(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ApiResponse<List<TravelMemberResponse>> =
		ApiResponse.success(travelMemberQueryService.getTravelMembers(travelId, principal.userId))
}
