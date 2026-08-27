package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommentCreateRequest
import com.ktcloud.travelplanner.community.dto.CommentResponse
import com.ktcloud.travelplanner.community.dto.MyCommentResponse
import com.ktcloud.travelplanner.community.model.CommunityComment
import com.ktcloud.travelplanner.community.repository.CommunityCommentRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.global.util.toExclusiveEndOfDayInstant
import com.ktcloud.travelplanner.global.util.toStartOfDayInstant
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.data.domain.PageRequest
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
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
		val comments = communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId)
		if (comments.isEmpty()) return emptyList()

		// 댓글마다 countReactions/existsReaction을 따로 부르면 N+1이라 배치로 한 번에 가져온다.
		val commentIds = comments.map { it.id }
		val reactionCounts = communityCommentRepository.countReactionsByCommentIds(commentIds)
			.associate { it.commentId to it.reactionCount }
		val reactedCommentIds = if (requesterId != null) {
			communityCommentRepository.findReactedCommentIds(commentIds, requesterId).toSet()
		} else {
			emptySet()
		}

		return comments.map { comment ->
			CommentResponse.from(
				comment = comment,
				isMine = requesterId != null && requesterId == comment.author.id,
				reactionCount = reactionCounts[comment.id] ?: 0L,
				isReacted = comment.id in reactedCommentIds,
			)
		}
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
		return CommentResponse.from(saved, isMine = true, reactionCount = 0, isReacted = false)
	}

	// PATCH /comments/{commentId} — 작성자 본인만, 내용만 바꿀 수 있다(카테고리/게시글 이동 없음).
	@Transactional
	fun updateComment(
		commentId: UUID,
		requesterId: UUID,
		request: CommentCreateRequest,
	): CommentResponse {
		val comment = communityCommentRepository.findById(commentId).orElseThrow(::CommunityCommentNotFoundException)
		if (comment.author.id != requesterId) {
			throw CommunityCommentAccessDeniedException()
		}
		comment.edit(request.content, Instant.now())

		val reactionCount = communityCommentRepository.countReactions(commentId)
		val isReacted = communityCommentRepository.existsReaction(commentId, requesterId)
		return CommentResponse.from(comment, isMine = true, reactionCount = reactionCount, isReacted = isReacted)
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

	// PUT /comments/{commentId}/reactions/{type} — 좋아요 토글. type은 현재 LIKE만
	// (community_comment_reaction의 ck_community_comment_reaction_type과 동일한 제약).
	// 이미 눌렀으면 취소, 안 눌렀으면 등록.
	@Transactional
	fun toggleReaction(
		commentId: UUID,
		requesterId: UUID,
		type: String,
	): CommentResponse {
		if (type != SUPPORTED_REACTION_TYPE) {
			throw UnsupportedCommentReactionTypeException()
		}
		val comment = communityCommentRepository.findById(commentId).orElseThrow(::CommunityCommentNotFoundException)

		val alreadyReacted = communityCommentRepository.existsReaction(commentId, requesterId)
		if (alreadyReacted) {
			communityCommentRepository.deleteReaction(commentId, requesterId)
		} else {
			communityCommentRepository.insertReaction(commentId, requesterId)
		}

		val reactionCount = communityCommentRepository.countReactions(commentId)
		return CommentResponse.from(
			comment = comment,
			isMine = requesterId == comment.author.id,
			reactionCount = reactionCount,
			isReacted = !alreadyReacted,
		)
	}

	// 마이페이지 "내가 쓴 댓글" 탭 — 본인 댓글만 작성일 역순으로. includeDeleted=true일 때만
	// 본인이 삭제한 댓글(및 삭제한 글에 달린 댓글)도 함께 보여준다(기본값 false). keyword/기간
	// 필터는 CommunityPostService.getMyPosts와 동일한 관례.
	@Transactional(readOnly = true)
	fun getMyComments(
		authorId: UUID,
		keyword: String?,
		periodStart: LocalDate?,
		periodEnd: LocalDate?,
		includeDeleted: Boolean,
		page: Int,
		size: Int,
	): PageResponse<MyCommentResponse> {
		val normalizedKeyword = keyword?.trim()?.takeIf { it.isNotEmpty() }
		val pageable = PageRequest.of(page.coerceAtLeast(0), size.coerceIn(MIN_PAGE_SIZE, MAX_PAGE_SIZE))
		val result = communityCommentRepository.findByAuthorIdIncludingDeletedOrderByCreatedAtDesc(
			authorId,
			normalizedKeyword,
			periodStart?.toStartOfDayInstant(),
			periodEnd?.toExclusiveEndOfDayInstant(),
			includeDeleted,
			pageable,
		)
		return PageResponse.from(result.map(MyCommentResponse::from))
	}

	companion object {
		private const val SUPPORTED_REACTION_TYPE = "LIKE"
		private const val MIN_PAGE_SIZE = 1
		private const val MAX_PAGE_SIZE = 50
	}
}

class CommunityCommentAuthorNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityCommentNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityCommentAccessDeniedException :
	DomainException(ErrorCode.ACCESS_DENIED, "본인 댓글만 수정·삭제할 수 있습니다.")

class UnsupportedCommentReactionTypeException :
	DomainException(ErrorCode.VALIDATION_ERROR, "지원하지 않는 리액션 타입입니다.")
