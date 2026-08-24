package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommentCreateRequest
import com.ktcloud.travelplanner.community.dto.CommentResponse
import com.ktcloud.travelplanner.community.service.CommunityCommentService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

// community-api-contract.md 2절 — 댓글이라는 같은 리소스에 대한 두 경로 그룹
// (/posts/{postId}/comments 목록·작성, /comments/{commentId} 삭제)을 한 컨트롤러에서 다룬다.
@RestController
@RequestMapping("/api/v1/community")
class CommunityCommentController(
	private val communityCommentService: CommunityCommentService,
) {
	// 인증 불필요. 로그인 상태면 isMine 계산을 위해 principal을 사용한다.
	@GetMapping("/posts/{postId}/comments")
	fun getComments(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal?,
		@PathVariable postId: UUID,
	): ApiResponse<List<CommentResponse>> =
		ApiResponse.success(communityCommentService.getComments(postId, principal?.userId))

	@PostMapping("/posts/{postId}/comments")
	fun createComment(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@PathVariable postId: UUID,
		@Valid @RequestBody request: CommentCreateRequest,
	): ApiResponse<CommentResponse> =
		ApiResponse.success(communityCommentService.createComment(postId, principal.userId, request))

	@DeleteMapping("/comments/{commentId}")
	fun deleteComment(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@PathVariable commentId: UUID,
	): ApiResponse<Unit> {
		communityCommentService.deleteComment(commentId, principal.userId)
		return ApiResponse.success(Unit)
	}
}
