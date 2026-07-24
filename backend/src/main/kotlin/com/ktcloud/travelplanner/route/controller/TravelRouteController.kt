package com.ktcloud.travelplanner.route.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.route.dto.TravelRouteResponse
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.service.TravelRouteService
import org.springframework.http.CacheControl
import org.springframework.http.ResponseEntity
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/travels/{travelId}/routes")
class TravelRouteController(
	private val travelRouteService: TravelRouteService,
) {
	@GetMapping
	fun getRoute(
		@PathVariable travelId: java.util.UUID,
		@RequestParam dayNumber: Int,
		@RequestParam transportationType: TransportationType,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
	): ResponseEntity<ApiResponse<TravelRouteResponse>> = ResponseEntity.ok()
		.cacheControl(CacheControl.noStore())
		.body(
			ApiResponse.success(
				travelRouteService.getRoute(travelId, principal.userId, dayNumber, transportationType),
			),
		)
}
