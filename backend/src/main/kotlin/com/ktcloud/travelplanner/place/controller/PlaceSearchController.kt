package com.ktcloud.travelplanner.place.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.place.dto.PlaceSearchResultResponse
import com.ktcloud.travelplanner.place.service.PlaceSearchService
import org.springframework.http.CacheControl
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/places")
class PlaceSearchController(
	private val placeSearchService: PlaceSearchService,
) {
	@GetMapping("/search")
	fun searchPlaces(
		@RequestParam query: String,
		@RequestParam countryCode: String,
	): ResponseEntity<ApiResponse<List<PlaceSearchResultResponse>>> = ResponseEntity.ok()
		.cacheControl(CacheControl.noStore())
		.body(ApiResponse.success(placeSearchService.searchPlaces(query, countryCode)))
}
