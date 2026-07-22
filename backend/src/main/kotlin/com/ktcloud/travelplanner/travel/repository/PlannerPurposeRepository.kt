package com.ktcloud.travelplanner.travel.repository

import com.ktcloud.travelplanner.travel.model.PlannerPurpose
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface PlannerPurposeRepository : JpaRepository<PlannerPurpose, UUID> {
        fun findAllByTravelId(travelId: UUID): List<PlannerPurpose>
        fun deleteAllByTravelId(travelId: UUID)
}
