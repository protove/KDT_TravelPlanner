package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityPost
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface CommunityPostRepository : JpaRepository<CommunityPost, UUID> {
	// community-api-contract.md 3절 — 기본 정렬. category/tag/keyword는 null이면 조건에서 제외된다.
	@Query(
		value = """
			SELECT new com.ktcloud.travelplanner.community.repository.CommunityPostListRow(
				post.id,
				category.code,
				post.title,
				post.bodyPreview,
				author.nickname,
				author.profileImageUrl,
				post.viewCount,
				post.sourceTravelId,
				post.createdAt
			)
			FROM CommunityPost post
			JOIN post.category category
			JOIN post.author author
			WHERE (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (SELECT 1 FROM post.tags t WHERE t.name = :tagName))
				AND (:keyword IS NULL OR LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
			ORDER BY post.createdAt DESC
		""",
		countQuery = """
			SELECT COUNT(post)
			FROM CommunityPost post
			JOIN post.category category
			WHERE (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (SELECT 1 FROM post.tags t WHERE t.name = :tagName))
				AND (:keyword IS NULL OR LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
		""",
	)
	fun findPostsOrderByCreatedAt(
		@Param("categoryCode") categoryCode: String?,
		@Param("tagName") tagName: String?,
		@Param("keyword") keyword: String?,
		pageable: Pageable,
	): Page<CommunityPostListRow>

	// community-api-contract.md 3절 — sort=popular: (reactionCount*2 + commentCount) DESC, createdAt DESC.
	// 댓글/리액션 API가 아직 붙지 않아(8절) reactionCount/commentCount는 0으로 고정되므로, 정렬식은
	// 지금은 상수(0 * 2 + 0)로 평가된다. 2차에서 두 테이블을 서브쿼리로 연결하면 이 식만 채워 넣으면 된다.
	@Query(
		value = """
			SELECT new com.ktcloud.travelplanner.community.repository.CommunityPostListRow(
				post.id,
				category.code,
				post.title,
				post.bodyPreview,
				author.nickname,
				author.profileImageUrl,
				post.viewCount,
				post.sourceTravelId,
				post.createdAt
			)
			FROM CommunityPost post
			JOIN post.category category
			JOIN post.author author
			WHERE (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (SELECT 1 FROM post.tags t WHERE t.name = :tagName))
				AND (:keyword IS NULL OR LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
			ORDER BY (0 * 2 + 0) DESC, post.createdAt DESC
		""",
		countQuery = """
			SELECT COUNT(post)
			FROM CommunityPost post
			JOIN post.category category
			WHERE (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (SELECT 1 FROM post.tags t WHERE t.name = :tagName))
				AND (:keyword IS NULL OR LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
		""",
	)
	fun findPostsOrderByPopularity(
		@Param("categoryCode") categoryCode: String?,
		@Param("tagName") tagName: String?,
		@Param("keyword") keyword: String?,
		pageable: Pageable,
	): Page<CommunityPostListRow>

	@Query(
		value = """
			SELECT new com.ktcloud.travelplanner.community.repository.CommunityPostTagNameRow(post.id, t.name)
			FROM CommunityPost post
			JOIN post.tags t
			WHERE post.id IN :postIds
		""",
	)
	fun findTagNamesByPostIds(
		@Param("postIds") postIds: List<UUID>,
	): List<CommunityPostTagNameRow>

	// view_count는 조회할 때마다 증가하므로 PATCH의 낙관적 락(@Version)과 별개로 다뤄야 한다.
	// 벌크 업데이트로 처리해 영속성 컨텍스트의 version을 건드리지 않는다.
	@Modifying
	@Query("UPDATE CommunityPost p SET p.viewCount = p.viewCount + 1 WHERE p.id = :postId")
	fun incrementViewCount(
		@Param("postId") postId: UUID,
	): Int

	@Query(
		value = "SELECT COUNT(*) FROM community_comment WHERE post_id = :postId AND deleted_at IS NULL",
		nativeQuery = true,
	)
	fun countActiveComments(
		@Param("postId") postId: UUID,
	): Long

	@Query(
		value = "SELECT COUNT(*) FROM community_reaction WHERE post_id = :postId",
		nativeQuery = true,
	)
	fun countReactions(
		@Param("postId") postId: UUID,
	): Long
}
