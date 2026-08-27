package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostDetailResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostReactionResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostSummaryResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostUpdateRequest
import com.ktcloud.travelplanner.community.service.CommunityPostService
import com.ktcloud.travelplanner.global.response.ApiResponse
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.global.security.AuthenticatedUserPrincipal
import jakarta.validation.Valid
import org.springframework.security.core.annotation.AuthenticationPrincipal
import org.springframework.web.bind.annotation.DeleteMapping
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PatchMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.PutMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import java.time.LocalDate
import java.util.UUID

// community-api-contract.md 2절 엔드포인트 표의 /api/v1/community/posts 그룹.
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

	// community-api-contract.md 2절/3절 — 인증 불필요. size 기본 10/최대 50은 서비스에서 clamp한다.
	// periodStart/periodEnd(YYYY-MM-DD)는 둘 다 없으면 전체 기간 조회 — 화면에서는 기본으로
	// 좁힌 기간을 보내되, 계약 자체는 무제한 조회도 허용한다.
	@GetMapping
	fun getPosts(
		@RequestParam(required = false) category: String?,
		@RequestParam(required = false) tag: String?,
		@RequestParam(required = false) keyword: String?,
		// keyword 매칭 대상. ALL(기본)/TITLE/AUTHOR/CONTENT/TAG — 화이트리스트 밖 값은 서비스에서 ALL로 처리.
		@RequestParam(required = false) searchScope: String?,
		@RequestParam(required = false) sort: String?,
		@RequestParam(required = false) periodStart: LocalDate?,
		@RequestParam(required = false) periodEnd: LocalDate?,
		@RequestParam(defaultValue = "0") page: Int,
		@RequestParam(defaultValue = "10") size: Int,
	): ApiResponse<PageResponse<CommunityPostSummaryResponse>> =
		ApiResponse.success(
			communityPostService.getPosts(
				category,
				tag,
				keyword,
				searchScope,
				sort,
				periodStart,
				periodEnd,
				page,
				size,
			),
		)

	// community-api-contract.md 2절 — 인증 불필요. 로그인 상태면 isMine 계산을 위해 principal을 사용한다.
	@GetMapping("/{postId}")
	fun getPostDetail(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal?,
		@PathVariable postId: UUID,
	): ApiResponse<CommunityPostDetailResponse> =
		ApiResponse.success(communityPostService.getPostDetail(postId, principal?.userId))

	// community-api-contract.md 2절 — 작성자 본인만, version 낙관적 락(불일치 시 409).
	@PatchMapping("/{postId}")
	fun updatePost(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@PathVariable postId: UUID,
		@Valid @RequestBody request: CommunityPostUpdateRequest,
	): ApiResponse<CommunityPostDetailResponse> =
		ApiResponse.success(communityPostService.updatePost(postId, principal.userId, request))

	// community-api-contract.md 2절 — 작성자 본인만, 소프트 삭제.
	@DeleteMapping("/{postId}")
	fun deletePost(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@PathVariable postId: UUID,
	): ApiResponse<Unit> {
		communityPostService.deletePost(postId, principal.userId)
		return ApiResponse.success(Unit)
	}

	// community-api-contract.md 2절 — 좋아요 토글. type은 현재 LIKE만, 로그인 필요.
	@PutMapping("/{postId}/reactions/{type}")
	fun toggleReaction(
		@AuthenticationPrincipal principal: AuthenticatedUserPrincipal,
		@PathVariable postId: UUID,
		@PathVariable type: String,
	): ApiResponse<CommunityPostReactionResponse> =
		ApiResponse.success(communityPostService.toggleReaction(postId, principal.userId, type))
}
