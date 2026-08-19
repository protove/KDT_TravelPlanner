package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityCategory
import org.springframework.data.jpa.repository.JpaRepository

interface CommunityCategoryRepository : JpaRepository<CommunityCategory, Short> {
	fun findByCodeAndIsActiveTrue(code: String): CommunityCategory?
}
