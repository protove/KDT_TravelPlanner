package com.ktcloud.travelplanner.community.dto

// PUT /posts/{postId}/reactions/{type} 응답. bodyJson까지 포함된 무거운 상세 응답 대신,
// 좋아요 토글에 실제로 필요한 두 값만 담는다(CommentResponse는 댓글 자체가 가벼워 전체를
// 돌려줘도 무방하지만, 게시글은 본문이 커서 굳이 다시 실어 보내지 않는다).
data class CommunityPostReactionResponse(
	val reactionCount: Long,
	val isReacted: Boolean,
)
