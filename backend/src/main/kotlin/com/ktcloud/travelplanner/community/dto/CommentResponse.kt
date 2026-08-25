package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.model.CommunityComment
import java.time.Instant
import java.util.UUID

// community-api-contract.md 1절 CommentResponse를 기반으로, 댓글 좋아요/수정 기능 추가에 맞춰
// updatedAt(수정 여부 표시용)·reactionCount·isReacted를 확장했다(계약 문서에는 아직 반영 안 됨).
data class CommentResponse(
	val commentId: UUID,
	val authorNickname: String?,
	val authorProfileImageUrl: String?,
	val content: String,
	val createdAt: Instant,
	val updatedAt: Instant?,
	val reactionCount: Long,
	val isReacted: Boolean,
	val isMine: Boolean,
) {
	companion object {
		fun from(
			comment: CommunityComment,
			isMine: Boolean,
			reactionCount: Long,
			isReacted: Boolean,
		): CommentResponse = CommentResponse(
			commentId = comment.id,
			authorNickname = comment.author.nickname,
			authorProfileImageUrl = comment.author.profileImageUrl,
			content = comment.content,
			createdAt = comment.createdAt,
			updatedAt = comment.updatedAt,
			reactionCount = reactionCount,
			isReacted = isReacted,
			isMine = isMine,
		)
	}
}
