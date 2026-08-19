package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityPost
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface CommunityPostRepository : JpaRepository<CommunityPost, UUID> {
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
