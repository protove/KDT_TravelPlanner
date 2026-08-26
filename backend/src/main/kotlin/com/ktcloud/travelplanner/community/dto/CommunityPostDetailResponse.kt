package com.ktcloud.travelplanner.community.dto

import com.fasterxml.jackson.databind.JsonNode
import com.ktcloud.travelplanner.community.model.CommunityPost
import java.time.Instant
import java.util.UUID

// community-api-contract.md 1절 CommunityPostDetail.
data class CommunityPostDetailResponse(
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
	val bodyJson: JsonNode,
	val itinerarySnapshotJson: JsonNode?,
	val isMine: Boolean,
	/** 로그인한 요청자가 이 게시글에 좋아요를 눌렀는지. 비로그인 조회 시 항상 false. */
	val isReacted: Boolean,
	// PATCH /posts/{postId}의 낙관적 락(version)에 그대로 되돌려 보내야 해서 상세 응답에 노출한다.
	val version: Int,
) {
	companion object {
		fun from(
			post: CommunityPost,
			bodyJson: JsonNode,
			itinerarySnapshotJson: JsonNode?,
			viewCount: Int,
			commentCount: Long,
			reactionCount: Long,
			isMine: Boolean,
			isReacted: Boolean,
		): CommunityPostDetailResponse = CommunityPostDetailResponse(
			postId = post.id,
			categoryCode = post.category.code,
			title = post.title,
			bodyPreview = post.bodyPreview,
			tags = post.tags.map { it.name },
			authorNickname = post.author.nickname,
			authorProfileImageUrl = post.author.profileImageUrl,
			viewCount = viewCount,
			commentCount = commentCount,
			reactionCount = reactionCount,
			sourceTravelId = post.sourceTravelId,
			createdAt = post.createdAt,
			bodyJson = bodyJson,
			itinerarySnapshotJson = itinerarySnapshotJson,
			isMine = isMine,
			isReacted = isReacted,
			version = post.version,
		)
	}
}
