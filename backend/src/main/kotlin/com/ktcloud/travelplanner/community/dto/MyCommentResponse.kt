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
	// 본인이 삭제한 댓글이면 값이 들어간다.
	val deletedAt: Instant?,
	// 댓글은 안 지웠는데 글이 삭제된 경우 값이 들어간다 — 프론트에서 상세 링크로 못 들어가게
	// 막는 용도(삭제된 글의 상세 조회는 404).
	val postDeletedAt: Instant?,
) {
	companion object {
		fun from(row: MyCommentRow): MyCommentResponse = MyCommentResponse(
			commentId = row.commentId,
			postId = row.postId,
			postTitle = row.postTitle,
			content = row.content,
			createdAt = row.createdAt,
			updatedAt = row.updatedAt,
			deletedAt = row.deletedAt,
			postDeletedAt = row.postDeletedAt,
		)
	}
}
