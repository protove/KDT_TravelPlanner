package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateResponse
import com.ktcloud.travelplanner.community.service.CommunityPostService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

// community-api-contract.md 2절 엔드포인트 표의 /api/v1/community/posts 그룹.
// 이 브랜치가 최초로 만드는 파일 — 이후 목록/상세/수정/삭제 메서드가 여기에 추가될 예정.
@RestController
@RequestMapping("/api/v1/community/posts")
class CommunityPostController(
	private val communityPostService: CommunityPostService,
) {
	@PostMapping
	fun createPost(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@Valid @RequestBody request: CommunityPostCreateRequest,
	): ApiResponse<CommunityPostCreateResponse> =
		ApiResponse.success(communityPostService.createPost(principal.userId, request))
}
