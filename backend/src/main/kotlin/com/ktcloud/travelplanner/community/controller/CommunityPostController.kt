package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostDetailResponse
import com.ktcloud.travelplanner.community.service.CommunityPostService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

// community-api-contract.md 2절 엔드포인트 표의 /api/v1/community/posts 그룹.
// 이후 목록/수정/삭제 메서드가 여기에 추가될 예정.
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

	// community-api-contract.md 2절 — 인증 불필요. 로그인 상태면 isMine 계산을 위해 principal을 사용한다.
	@GetMapping("/{postId}")
	fun getPostDetail(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal?,
		@PathVariable postId: UUID,
	): ApiResponse<CommunityPostDetailResponse> =
		ApiResponse.success(communityPostService.getPostDetail(postId, principal?.userId))
}
