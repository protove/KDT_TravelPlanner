package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.model.CommunityComment
import java.time.Instant
import java.util.UUID

// community-api-contract.md 1절 CommentResponse.
data class CommentResponse(
	val commentId: UUID,
	val authorNickname: String?,
	val authorProfileImageUrl: String?,
	val content: String,
	val createdAt: Instant,
	val isMine: Boolean,
) {
	companion object {
		fun from(
			comment: CommunityComment,
			isMine: Boolean,
		): CommentResponse = CommentResponse(
			commentId = comment.id,
			authorNickname = comment.author.nickname,
			authorProfileImageUrl = comment.author.profileImageUrl,
			content = comment.content,
			createdAt = comment.createdAt,
			isMine = isMine,
		)
	}
}
