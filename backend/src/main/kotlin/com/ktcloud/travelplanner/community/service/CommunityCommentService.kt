package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommentCreateRequest
import com.ktcloud.travelplanner.community.dto.CommentResponse
import com.ktcloud.travelplanner.community.model.CommunityComment
import com.ktcloud.travelplanner.community.repository.CommunityCommentRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.util.UUID

@Service
class CommunityCommentService(
	private val communityPostRepository: CommunityPostRepository,
	private val communityCommentRepository: CommunityCommentRepository,
	private val userRepository: UserRepository,
) {
	// community-api-contract.md 2절 — 댓글 목록. 단일 depth, 페이지네이션 없음, 인증 불필요.
	// 게시글이 없거나 소프트 삭제된 경우 404(CommunityPost의 @SQLRestriction이 findById에서 걸러줌).
	// existsById는 쓰지 않는다 — getPostDetail에서 겪었던 "존재 확인과 조회를 분리했다가 스텁 누락으로
	// 항상 404가 나던" 버그와 같은 종류의 문제를 애초에 만들지 않기 위함.
	@Transactional(readOnly = true)
	fun getComments(
		postId: UUID,
		requesterId: UUID?,
	): List<CommentResponse> {
		communityPostRepository.findById(postId).orElseThrow(::CommunityPostNotFoundException)
		return communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId)
			.map { comment -> CommentResponse.from(comment, requesterId != null && requesterId == comment.author.id) }
	}

	@Transactional
	fun createComment(
		postId: UUID,
		authorId: UUID,
		request: CommentCreateRequest,
	): CommentResponse {
		val post = communityPostRepository.findById(postId).orElseThrow(::CommunityPostNotFoundException)
		val author = userRepository.findById(authorId).orElseThrow(::CommunityCommentAuthorNotFoundException)

		val comment = CommunityComment(
			post = post,
			author = author,
			content = request.content,
		)
		val saved = communityCommentRepository.save(comment)
		return CommentResponse.from(saved, isMine = true)
	}

	// community-api-contract.md 2절 — 댓글 삭제(soft), 작성자 본인만.
	@Transactional
	fun deleteComment(
		commentId: UUID,
		requesterId: UUID,
	) {
		val comment = communityCommentRepository.findById(commentId).orElseThrow(::CommunityCommentNotFoundException)
		if (comment.author.id != requesterId) {
			throw CommunityCommentAccessDeniedException()
		}
		comment.softDelete(Instant.now())
	}
}

class CommunityCommentAuthorNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityCommentNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityCommentAccessDeniedException :
	DomainException(ErrorCode.ACCESS_DENIED, "본인 댓글만 삭제할 수 있습니다.")
