package com.ktcloud.travelplanner.travel.repository

import com.ktcloud.travelplanner.travel.model.Travel
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface TravelRepository : JpaRepository<Travel, UUID>
