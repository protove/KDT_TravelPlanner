package com.ktcloud.travelplanner.travel.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.travel.dto.TravelCreateRequest
import com.ktcloud.travelplanner.travel.dto.TravelCreateResponse
import com.ktcloud.travelplanner.travel.dto.TravelDetailResponse
import com.ktcloud.travelplanner.travel.dto.TravelSummaryResponse
import com.ktcloud.travelplanner.travel.dto.TravelUpdateRequest
import com.ktcloud.travelplanner.travel.service.TravelDetailService
import com.ktcloud.travelplanner.travel.service.TravelService
import com.ktcloud.travelplanner.travel.service.TravelUpdateService
import jakarta.validation.Valid
import jakarta.validation.constraints.Max
import jakarta.validation.constraints.Min
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.validation.annotation.Validated
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@Validated
@RestController
@RequestMapping("/api/v1/travels")
class TravelController(
	private val travelService: TravelService,
	private val travelDetailService: TravelDetailService,
	private val travelUpdateService: TravelUpdateService,
) {
	@PostMapping
	fun createTravel(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@Valid @RequestBody request: TravelCreateRequest,
	): ApiResponse<TravelCreateResponse> =
		ApiResponse.success(travelService.createTravel(principal.userId, request))

	@GetMapping
	fun getTravels(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestParam(required = false) keyword: String?,
		@RequestParam(defaultValue = "0") @Min(0) page: Int,
		@RequestParam(defaultValue = "20") @Min(1) @Max(100) size: Int,
	): ApiResponse<PageResponse<TravelSummaryResponse>> =
		ApiResponse.success(travelService.getTravels(principal.userId, keyword, page, size))

	@GetMapping("/{travelId}")
	fun getTravelDetail(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ApiResponse<TravelDetailResponse> =
		ApiResponse.success(travelDetailService.getTravelDetail(travelId, principal.userId))

	@PatchMapping("/{travelId}")
	fun updateTravel(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@Valid @RequestBody request: TravelUpdateRequest,
	): ApiResponse<TravelDetailResponse> =
		ApiResponse.success(travelUpdateService.updateTravel(travelId, principal.userId, request))

	@DeleteMapping("/{travelId}")
	fun deleteTravel(
		@PathVariable travelId: UUID,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ApiResponse<Unit> {
		travelService.deleteTravel(travelId, principal.userId)
		return ApiResponse.success(Unit)
	}
}
