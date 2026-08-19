package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.repository.CommunityPostListRow
import java.time.Instant
import java.util.UUID

// community-api-contract.md 1절 CommunityPostSummary.
data class CommunityPostSummaryResponse(
	val postId: UUID,
	val categoryCode: String,
	val title: String,
	val bodyPreview: String?,
	val tags: List<String>,
	val authorNickname: String?,
	val authorProfileImageUrl: String?,
	val viewCount: Int,
	val commentCount: Long,
	val reactionCount: Long,
	val sourceTravelId: UUID?,
	val createdAt: Instant,
) {
	companion object {
		// community-api-contract.md 3절/8절 — 댓글/리액션 API가 아직 붙지 않아 목록 조회에서는 0으로 고정한다.
		// sort=popular 정렬식(CommunityPostRepository.findPostsOrderByPopularity)은 이 값들이 채워지는
		// 시점에 자연히 맞아떨어지도록 이미 (reactionCount*2 + commentCount) 형태로 맞춰 두었다.
		fun from(
			row: CommunityPostListRow,
			tags: List<String>,
		): CommunityPostSummaryResponse = CommunityPostSummaryResponse(
			postId = row.postId,
			categoryCode = row.categoryCode,
			title = row.title,
			bodyPreview = row.bodyPreview,
			tags = tags,
			authorNickname = row.authorNickname,
			authorProfileImageUrl = row.authorProfileImageUrl,
			viewCount = row.viewCount,
			commentCount = 0,
			reactionCount = 0,
			sourceTravelId = row.sourceTravelId,
			createdAt = row.createdAt,
		)
	}
}
