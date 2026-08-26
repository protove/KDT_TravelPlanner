package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommunityPostSummaryResponse
import com.ktcloud.travelplanner.community.dto.MyCommentResponse
import com.ktcloud.travelplanner.community.service.CommunityCommentService
import com.ktcloud.travelplanner.community.service.CommunityPostService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController

// 마이페이지 "내가 쓴 글"/"내가 쓴 댓글" 탭 전용. /api/v1/community/posts/* 는 SecurityConfig에서
// permitAll 와일드카드로 열려 있어 그 아래에 /posts/me 식으로 붙이면 인증 없이 노출될 위험이 있다 —
// 그래서 별도 /me 하위 경로로 분리해 /api/** 의 authenticated() 규칙에 자연히 걸리게 한다.
@RestController
@RequestMapping("/api/v1/community/me")
class MyCommunityController(
	private val communityPostService: CommunityPostService,
	private val communityCommentService: CommunityCommentService,
) {
	@GetMapping("/posts")
	fun getMyPosts(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestParam(defaultValue = "0") page: Int,
		@RequestParam(defaultValue = "10") size: Int,
	): ApiResponse<PageResponse<CommunityPostSummaryResponse>> =
		ApiResponse.success(communityPostService.getMyPosts(principal.userId, page, size))

	@GetMapping("/comments")
	fun getMyComments(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@RequestParam(defaultValue = "0") page: Int,
		@RequestParam(defaultValue = "10") size: Int,
	): ApiResponse<PageResponse<MyCommentResponse>> =
		ApiResponse.success(communityCommentService.getMyComments(principal.userId, page, size))
}
