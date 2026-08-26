package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommunityCategoryResponse
import com.ktcloud.travelplanner.community.service.CommunityCategoryService
import com.ktcloud.travelplanner.global.response.ApiResponse
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/community/categories")
class CommunityCategoryController(
	private val communityCategoryService: CommunityCategoryService,
) {
	@GetMapping
	fun getCategories(
		@RequestParam(defaultValue = "false") excludeNotice: Boolean,
	): ApiResponse<List<CommunityCategoryResponse>> =
		ApiResponse.success(communityCategoryService.getCategories(excludeNotice))
}
