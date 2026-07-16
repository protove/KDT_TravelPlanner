package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.membership.dto.TravelMemberResponse
import com.ktcloud.travelplanner.membership.dto.TravelMemberRoleUpdateRequest
import com.ktcloud.travelplanner.membership.service.TravelMemberQueryService
import com.ktcloud.travelplanner.membership.service.TravelMemberService
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travels/{travelId}/members")
class TravelMemberController(
	private val travelMemberQueryService: TravelMemberQueryService,
	private val travelMemberService: TravelMemberService,
) {
	@DeleteMapping("/{memberId}")
	fun removeMember(
		@PathVariable travelId: UUID,
		@PathVariable memberId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ApiResponse<Unit> {
		travelMemberService.removeMember(travelId, memberId, principal.userId)
		return ApiResponse.success(Unit)
	}

	@PatchMapping("/{memberId}")
	fun updateMemberRole(
		@PathVariable travelId: UUID,
		@PathVariable memberId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestBody request: TravelMemberRoleUpdateRequest,
	): ApiResponse<TravelMemberResponse> =
		ApiResponse.success(travelMemberService.updateMemberRole(travelId, memberId, principal.userId, request))

	@GetMapping
	fun getTravelMembers(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ApiResponse<List<TravelMemberResponse>> =
		ApiResponse.success(travelMemberQueryService.getTravelMembers(travelId, principal.userId))
}
