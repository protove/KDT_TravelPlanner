package com.ktcloud.travelplanner.location.controller

import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.location.dto.CityResponse
import com.ktcloud.travelplanner.location.dto.CountryResponse
import com.ktcloud.travelplanner.location.service.LocationCatalogService
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/countries")
class LocationController(
	private val locationCatalogService: LocationCatalogService,
) {
	@GetMapping
	fun getCountries(): ApiResponse<List<CountryResponse>> =
		ApiResponse.success(locationCatalogService.getCountries())

	@GetMapping("/{countryId}/cities")
	fun getCities(
		@PathVariable countryId: Short,
	): ApiResponse<List<CityResponse>> =
		ApiResponse.success(locationCatalogService.getCities(countryId))
}
