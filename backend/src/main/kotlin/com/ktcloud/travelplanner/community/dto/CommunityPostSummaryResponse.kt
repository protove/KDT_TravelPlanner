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
		fun from(
			row: CommunityPostListRow,
			tags: List<String>,
			commentCount: Long,
			reactionCount: Long,
		): CommunityPostSummaryResponse = CommunityPostSummaryResponse(
			postId = row.postId,
			categoryCode = row.categoryCode,
			title = row.title,
			bodyPreview = row.bodyPreview,
			tags = tags,
			authorNickname = row.authorNickname,
			authorProfileImageUrl = row.authorProfileImageUrl,
			viewCount = row.viewCount,
			commentCount = commentCount,
			reactionCount = reactionCount,
			sourceTravelId = row.sourceTravelId,
			createdAt = row.createdAt,
		)
	}
}
