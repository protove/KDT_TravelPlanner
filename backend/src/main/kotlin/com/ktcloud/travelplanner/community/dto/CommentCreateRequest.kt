package com.ktcloud.travelplanner.community.dto

import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size

// community-api-contract.md 1절 CommentCreateRequest.
// content 최대 길이는 계약서에 명시되어 있지 않다 — DB 컬럼은 TEXT(무제한)이지만, 어뷰징 방지를
// 위해 게시글 title(200자)보다 넉넉한 1000자로 서버에서 제한한다.
// 댓글 수정(PATCH /comments/{commentId}) 요청도 필드가 완전히 동일해서 별도 DTO 없이 재사용한다.
data class CommentCreateRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	@field:Size(max = 1000, message = "1000자 이하여야 합니다.")
	val content: String,
)
