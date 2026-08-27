package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.model.CommunityComment
import com.ktcloud.travelplanner.community.port.AuthorSummary
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
		// 목록 조회(getComments) 전용 — CommunityCommentRepository가 이미 JOIN FETCH로 author를
		// 같이 가져오므로, 여기서 Port를 거치면 댓글 수만큼 N+1 조회가 생긴다. 그래서 이 경로는
		// 의도적으로 엔티티에서 직접 읽는다(MSA 분리 시 목록 API의 배치 조회 최적화가 별도 필요 —
		// docs/msa-implementation-plan.md 참고).
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

		// 단건 조회/변경(createComment/updateComment/toggleReaction) 전용 — UserLookupPort로 가져온
		// AuthorSummary를 쓴다. 단건이라 배치 문제가 없고, 이 경로가 실제 서비스 분리 시 HTTP
		// Adapter로 그대로 교체된다.
		fun from(
			comment: CommunityComment,
			author: AuthorSummary?,
			isMine: Boolean,
			reactionCount: Long,
			isReacted: Boolean,
		): CommentResponse = CommentResponse(
			commentId = comment.id,
			authorNickname = author?.nickname,
			authorProfileImageUrl = author?.profileImageUrl,
			content = comment.content,
			createdAt = comment.createdAt,
			updatedAt = comment.updatedAt,
			reactionCount = reactionCount,
			isReacted = isReacted,
			isMine = isMine,
		)
	}
}
