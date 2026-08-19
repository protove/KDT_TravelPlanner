package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityTag
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param

interface CommunityTagRepository : JpaRepository<CommunityTag, Long> {
	fun findByName(name: String): CommunityTag?

	// find-or-create 규칙(community-api-contract.md 4절): 동시 요청이 같은 신규 태그명을 먼저
	// 만들려고 경합해도 ON CONFLICT DO NOTHING으로 유니크 제약 위반 없이 하나만 살아남는다.
	@Modifying
	@Query(value = "INSERT INTO community_tag (name) VALUES (:name) ON CONFLICT (name) DO NOTHING", nativeQuery = true)
	fun insertIgnoringConflict(@Param("name") name: String)
}
