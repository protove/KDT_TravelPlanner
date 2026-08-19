package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.community.model.CommunityPost
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface CommunityPostRepository : JpaRepository<CommunityPost, UUID>
