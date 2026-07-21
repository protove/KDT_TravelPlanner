package com.ktcloud.travelplanner.place.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import com.ktcloud.travelplanner.place.dto.TravelMapPointsResponse
import com.ktcloud.travelplanner.place.service.TravelMapPointService
import jakarta.servlet.http.HttpServletResponse
import org.springframework.http.CacheControl
import org.springframework.http.HttpHeaders
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@RestController
@RequestMapping("/api/v1/travels/{travelId}/map-points")
class TravelMapPointController(
	private val travelMapPointService: TravelMapPointService,
) {
	@GetMapping
	fun getMapPoints(
		@PathVariable travelId: UUID,
		@RequestParam dayNumber: Int,
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		response: HttpServletResponse,
	): ApiResponse<TravelMapPointsResponse> {
		response.setHeader(HttpHeaders.CACHE_CONTROL, CacheControl.noStore().headerValue)
		return ApiResponse.success(travelMapPointService.getMapPoints(travelId, principal.userId, dayNumber))
	}
}
