package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityTag
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Modifying
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param

interface CommunityTagRepository : JpaRepository<CommunityTag, Long> {
	fun findByName(name: String): CommunityTag?
	fun findByNameStartingWithIgnoreCaseOrderByName(keyword: String, pageable: Pageable): List<CommunityTag>

	@Modifying
	@Query(value = "INSERT INTO community_tag (name) VALUES (:name) ON CONFLICT (name) DO NOTHING", nativeQuery = true)
	fun insertIgnoringConflict(@Param("name") name: String)
}