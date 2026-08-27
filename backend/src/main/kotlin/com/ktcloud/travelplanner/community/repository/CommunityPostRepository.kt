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
	// searchScope(ALL/TITLE/AUTHOR/CONTENT/TAG)로 keyword 매칭 대상을 고른다 — CONTENT는 본문 전체(jsonb)가
	// 아니라 이미 평문으로 뽑아둔 bodyPreview(120자) 대상. searchScope 자체는 서비스에서 화이트리스트
	// 검증 후 넘어오므로 여기서는 그대로 비교만 한다.
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
				AND (:keyword IS NULL OR (
					(:searchScope = 'TITLE' AND LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'AUTHOR' AND LOWER(author.nickname) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'CONTENT' AND LOWER(post.bodyPreview) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'TAG' AND EXISTS (SELECT 1 FROM post.tags st WHERE LOWER(st.name) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))))
					OR (:searchScope = 'ALL' AND (
						LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR LOWER(author.nickname) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR LOWER(post.bodyPreview) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR EXISTS (SELECT 1 FROM post.tags st2 WHERE LOWER(st2.name) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					))
				))
			ORDER BY post.createdAt DESC
		""",
		countQuery = """
			SELECT COUNT(post)
			FROM CommunityPost post
			JOIN post.category category
			JOIN post.author author
			WHERE (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (SELECT 1 FROM post.tags t WHERE t.name = :tagName))
				AND (:keyword IS NULL OR (
					(:searchScope = 'TITLE' AND LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'AUTHOR' AND LOWER(author.nickname) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'CONTENT' AND LOWER(post.bodyPreview) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					OR (:searchScope = 'TAG' AND EXISTS (SELECT 1 FROM post.tags st WHERE LOWER(st.name) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))))
					OR (:searchScope = 'ALL' AND (
						LOWER(post.title) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR LOWER(author.nickname) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR LOWER(post.bodyPreview) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%'))
						OR EXISTS (SELECT 1 FROM post.tags st2 WHERE LOWER(st2.name) LIKE LOWER(CONCAT('%', CAST(:keyword AS string), '%')))
					))
				))
		""",
	)
	fun findPostsOrderByCreatedAt(
		@Param("categoryCode") categoryCode: String?,
		@Param("tagName") tagName: String?,
		@Param("keyword") keyword: String?,
		@Param("searchScope") searchScope: String,
		pageable: Pageable,
	): Page<CommunityPostListRow>

	// community-api-contract.md 3절 — sort=popular: (reactionCount*2 + commentCount) DESC, createdAt DESC.
	// community_reaction은 매핑된 JPA 엔티티가 없어(항상 네이티브로만 다룸, countReactions 등 참고)
	// JPQL "SELECT NEW" 방식으로는 이 정렬식을 표현할 수 없어서 쿼리 자체를 네이티브로 뺐다.
	// WHERE 절은 findPostsOrderByCreatedAt과 동일한 조건을 raw SQL로 옮긴 것 — @SQLRestriction이
	// 없어지는 만큼 post.deleted_at IS NULL을 직접 추가했다.
	@Query(
		value = """
			SELECT
				post.id AS postId,
				category.code AS categoryCode,
				post.title AS title,
				post.body_preview AS bodyPreview,
				author.nickname AS authorNickname,
				author.profile_image_url AS authorProfileImageUrl,
				post.view_count AS viewCount,
				post.source_travel_id AS sourceTravelId,
				post.created_at AS createdAt
			FROM community_post post
			JOIN community_category category ON category.id = post.category_id
			JOIN user_table author ON author.id = post.author_id
			WHERE post.deleted_at IS NULL
				AND (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (
					SELECT 1 FROM community_post_tag pt
					JOIN community_tag t ON t.id = pt.tag_id
					WHERE pt.post_id = post.id AND t.name = :tagName
				))
				AND (:keyword IS NULL OR (
					(:searchScope = 'TITLE' AND LOWER(post.title) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'AUTHOR' AND LOWER(author.nickname) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'CONTENT' AND LOWER(post.body_preview) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'TAG' AND EXISTS (
						SELECT 1 FROM community_post_tag pt2
						JOIN community_tag t2 ON t2.id = pt2.tag_id
						WHERE pt2.post_id = post.id AND LOWER(t2.name) LIKE LOWER(CONCAT('%', :keyword, '%'))
					))
					OR (:searchScope = 'ALL' AND (
						LOWER(post.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR LOWER(author.nickname) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR LOWER(post.body_preview) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR EXISTS (
							SELECT 1 FROM community_post_tag pt3
							JOIN community_tag t3 ON t3.id = pt3.tag_id
							WHERE pt3.post_id = post.id AND LOWER(t3.name) LIKE LOWER(CONCAT('%', :keyword, '%'))
						)
					))
				))
			ORDER BY (
				(SELECT COUNT(*) FROM community_reaction r WHERE r.post_id = post.id) * 2
				+ (SELECT COUNT(*) FROM community_comment c WHERE c.post_id = post.id AND c.deleted_at IS NULL)
			) DESC, post.created_at DESC
		""",
		countQuery = """
			SELECT COUNT(*)
			FROM community_post post
			JOIN community_category category ON category.id = post.category_id
			JOIN user_table author ON author.id = post.author_id
			WHERE post.deleted_at IS NULL
				AND (:categoryCode IS NULL OR category.code = :categoryCode)
				AND (:tagName IS NULL OR EXISTS (
					SELECT 1 FROM community_post_tag pt
					JOIN community_tag t ON t.id = pt.tag_id
					WHERE pt.post_id = post.id AND t.name = :tagName
				))
				AND (:keyword IS NULL OR (
					(:searchScope = 'TITLE' AND LOWER(post.title) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'AUTHOR' AND LOWER(author.nickname) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'CONTENT' AND LOWER(post.body_preview) LIKE LOWER(CONCAT('%', :keyword, '%')))
					OR (:searchScope = 'TAG' AND EXISTS (
						SELECT 1 FROM community_post_tag pt2
						JOIN community_tag t2 ON t2.id = pt2.tag_id
						WHERE pt2.post_id = post.id AND LOWER(t2.name) LIKE LOWER(CONCAT('%', :keyword, '%'))
					))
					OR (:searchScope = 'ALL' AND (
						LOWER(post.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR LOWER(author.nickname) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR LOWER(post.body_preview) LIKE LOWER(CONCAT('%', :keyword, '%'))
						OR EXISTS (
							SELECT 1 FROM community_post_tag pt3
							JOIN community_tag t3 ON t3.id = pt3.tag_id
							WHERE pt3.post_id = post.id AND LOWER(t3.name) LIKE LOWER(CONCAT('%', :keyword, '%'))
						)
					))
				))
		""",
		nativeQuery = true,
	)
	fun findPostsOrderByPopularity(
		@Param("categoryCode") categoryCode: String?,
		@Param("tagName") tagName: String?,
		@Param("keyword") keyword: String?,
		@Param("searchScope") searchScope: String,
		pageable: Pageable,
	): Page<PostSummaryRow>

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
	@Modifying(clearAutomatically = true)
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

	// community_comment_reaction과 동일한 구조를 post_id 기준으로 쓴다(CommunityCommentRepository 참고).
	@Query(
		value = "SELECT EXISTS(SELECT 1 FROM community_reaction WHERE post_id = :postId AND user_id = :userId)",
		nativeQuery = true,
	)
	fun existsReaction(
		@Param("postId") postId: UUID,
		@Param("userId") userId: UUID,
	): Boolean

	@Modifying
	@Query(
		value = "INSERT INTO community_reaction (post_id, user_id, type) VALUES (:postId, :userId, 'LIKE') " +
			"ON CONFLICT (post_id, user_id, type) DO NOTHING",
		nativeQuery = true,
	)
	fun insertReaction(
		@Param("postId") postId: UUID,
		@Param("userId") userId: UUID,
	): Int

	@Modifying
	@Query(value = "DELETE FROM community_reaction WHERE post_id = :postId AND user_id = :userId", nativeQuery = true)
	fun deleteReaction(
		@Param("postId") postId: UUID,
		@Param("userId") userId: UUID,
	): Int

	// 목록 조회에서 게시글마다 countActiveComments/countReactions를 따로 부르면 N+1이라
	// CommunityCommentRepository.countReactionsByCommentIds와 동일한 패턴으로 배치 조회한다.
	@Query(
		value = "SELECT post_id AS postId, COUNT(*) AS commentCount " +
			"FROM community_comment WHERE post_id IN (:postIds) AND deleted_at IS NULL GROUP BY post_id",
		nativeQuery = true,
	)
	fun countActiveCommentsByPostIds(
		@Param("postIds") postIds: List<UUID>,
	): List<PostCommentCountRow>

	@Query(
		value = "SELECT post_id AS postId, COUNT(*) AS reactionCount " +
			"FROM community_reaction WHERE post_id IN (:postIds) GROUP BY post_id",
		nativeQuery = true,
	)
	fun countReactionsByPostIds(
		@Param("postIds") postIds: List<UUID>,
	): List<PostReactionCountRow>

	// 마이페이지 "내가 쓴 글" 탭 — 카테고리/키워드 필터 없이 본인 글만 작성일 역순으로, 본인이
	// 소프트 삭제한 글도 함께 보여준다. CommunityPost의 @SQLRestriction("deleted_at IS NULL")은
	// JPQL로는(findById 포함) 절대 우회할 수 없어서, countActiveComments 등과 동일하게 네이티브
	// 쿼리로 우회한다.
	@Query(
		value = """
			SELECT
				post.id AS postId,
				category.code AS categoryCode,
				post.title AS title,
				post.body_preview AS bodyPreview,
				author.nickname AS authorNickname,
				author.profile_image_url AS authorProfileImageUrl,
				post.view_count AS viewCount,
				post.source_travel_id AS sourceTravelId,
				post.created_at AS createdAt,
				post.deleted_at AS deletedAt
			FROM community_post post
			JOIN community_category category ON category.id = post.category_id
			JOIN user_table author ON author.id = post.author_id
			WHERE post.author_id = :authorId
			ORDER BY post.created_at DESC
		""",
		countQuery = "SELECT COUNT(*) FROM community_post WHERE author_id = :authorId",
		nativeQuery = true,
	)
	fun findByAuthorIdIncludingDeletedOrderByCreatedAtDesc(
		@Param("authorId") authorId: UUID,
		pageable: Pageable,
	): Page<MyPostRow>
}

interface PostCommentCountRow {
	val postId: UUID
	val commentCount: Long
}

interface PostReactionCountRow {
	val postId: UUID
	val reactionCount: Long
}
