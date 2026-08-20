package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.service.CommunityTagService
import com.ktcloud.travelplanner.global.response.ApiResponse
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/community/tags")
class CommunityTagController(
	private val communityTagService: CommunityTagService,
) {
	@GetMapping
	fun getTags(
		@RequestParam(required = false, defaultValue = "") keyword: String,
		@RequestParam(required = false, defaultValue = "10") size: Int,
	): ApiResponse<List<String>> = ApiResponse.success(communityTagService.searchTagNames(keyword, size))
}
