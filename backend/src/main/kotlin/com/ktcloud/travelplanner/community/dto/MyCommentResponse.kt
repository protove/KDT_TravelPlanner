package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.repository.MyCommentRow
import java.time.Instant
import java.util.UUID

// 마이페이지 "내가 쓴 댓글" 탭 전용 응답 — 어느 글에 단 댓글인지 알아야 하므로 postId/postTitle을
// 들고 있다. 기존 CommentResponse(댓글 목록 API)와 달리 postId가 필요해 별도 DTO로 둔다.
data class MyCommentResponse(
	val commentId: UUID,
	val postId: UUID,
	val postTitle: String,
	val content: String,
	val createdAt: Instant,
	val updatedAt: Instant?,
) {
	companion object {
		fun from(row: MyCommentRow): MyCommentResponse = MyCommentResponse(
			commentId = row.commentId,
			postId = row.postId,
			postTitle = row.postTitle,
			content = row.content,
			createdAt = row.createdAt,
			updatedAt = row.updatedAt,
		)
	}
}
