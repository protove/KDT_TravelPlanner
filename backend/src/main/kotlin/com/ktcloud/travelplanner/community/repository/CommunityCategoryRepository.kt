package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityCategory
import org.springframework.data.jpa.repository.JpaRepository

interface CommunityCategoryRepository : JpaRepository<CommunityCategory, Short> {
	fun findAllByIsActiveTrueOrderBySortOrderAscIdAsc(): List<CommunityCategory>
	fun findAllByIsActiveTrueAndCodeNotOrderBySortOrderAscIdAsc(code: String): List<CommunityCategory>
	fun findByCodeAndIsActiveTrue(code: String): CommunityCategory?
}