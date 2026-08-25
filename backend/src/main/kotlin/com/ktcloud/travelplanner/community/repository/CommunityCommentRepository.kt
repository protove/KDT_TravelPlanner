package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityComment
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface CommunityCommentRepository : JpaRepository<CommunityComment, UUID> {
	// community-api-contract.md 2절 — 단일 depth, 페이지네이션 없이 작성순(오래된 순)으로 전부 반환.
	// author를 매번 LAZY 조회하지 않도록 JOIN FETCH로 함께 가져온다.
	@Query(
		value = """
			SELECT c FROM CommunityComment c
			JOIN FETCH c.author
			WHERE c.post.id = :postId
			ORDER BY c.createdAt ASC
		""",
	)
	fun findAllByPostIdOrderByCreatedAtAsc(
		@Param("postId") postId: UUID,
	): List<CommunityComment>

	// community_comment_reaction(V20)은 댓글 좋아요 전용 테이블 — post용 community_reaction과
	// 동일한 구조를 comment_id 기준으로 쓴다. 별도 엔티티로 매핑하지 않고 CommunityTagRepository.
	// insertIgnoringConflict, CommunityPostRepository.countActiveComments와 같은 패턴으로
	// 네이티브 쿼리만으로 다룬다. type은 현재 'LIKE' 하나뿐이라 컬럼 값을 고정해서 다룬다.
	@Query(value = "SELECT COUNT(*) FROM community_comment_reaction WHERE comment_id = :commentId", nativeQuery = true)
	fun countReactions(
		@Param("commentId") commentId: UUID,
	): Long

	@Query(
		value = "SELECT EXISTS(SELECT 1 FROM community_comment_reaction WHERE comment_id = :commentId AND user_id = :userId)",
		nativeQuery = true,
	)
	fun existsReaction(
		@Param("commentId") commentId: UUID,
		@Param("userId") userId: UUID,
	): Boolean

	@Modifying
	@Query(
		value = "INSERT INTO community_comment_reaction (comment_id, user_id, type) VALUES (:commentId, :userId, 'LIKE') " +
			"ON CONFLICT (comment_id, user_id, type) DO NOTHING",
		nativeQuery = true,
	)
	fun insertReaction(
		@Param("commentId") commentId: UUID,
		@Param("userId") userId: UUID,
	): Int

	@Modifying
	@Query(value = "DELETE FROM community_comment_reaction WHERE comment_id = :commentId AND user_id = :userId", nativeQuery = true)
	fun deleteReaction(
		@Param("commentId") commentId: UUID,
		@Param("userId") userId: UUID,
	): Int

	// 댓글 목록 조회에서 댓글마다 countReactions를 따로 부르는 N+1을 피하기 위한 배치 조회.
	@Query(
		value = "SELECT comment_id AS commentId, COUNT(*) AS reactionCount " +
			"FROM community_comment_reaction WHERE comment_id IN (:commentIds) GROUP BY comment_id",
		nativeQuery = true,
	)
	fun countReactionsByCommentIds(
		@Param("commentIds") commentIds: List<UUID>,
	): List<CommentReactionCountRow>

	@Query(
		value = "SELECT comment_id FROM community_comment_reaction WHERE comment_id IN (:commentIds) AND user_id = :userId",
		nativeQuery = true,
	)
	fun findReactedCommentIds(
		@Param("commentIds") commentIds: List<UUID>,
		@Param("userId") userId: UUID,
	): List<UUID>
}

// countReactionsByCommentIds의 네이티브 쿼리 결과를 매핑하는 Spring Data 인터페이스 프로젝션.
// 프로퍼티 이름(commentId/reactionCount)이 쿼리의 컬럼 별칭과 대소문자 무시로 매칭된다.
interface CommentReactionCountRow {
	val commentId: UUID
	val reactionCount: Long
}
