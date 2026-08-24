package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityComment
import org.springframework.data.jpa.repository.JpaRepository
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
}
