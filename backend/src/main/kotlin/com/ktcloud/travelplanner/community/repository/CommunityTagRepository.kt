package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityTag
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository

interface CommunityTagRepository : JpaRepository<CommunityTag, Long> {
	fun findByNameStartingWithIgnoreCaseOrderByName(keyword: String, pageable: Pageable): List<CommunityTag>
}
