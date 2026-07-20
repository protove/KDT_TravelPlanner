package com.ktcloud.travelplanner.travel.repository

import com.ktcloud.travelplanner.travel.model.Travel
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface TravelRepository : JpaRepository<Travel, UUID> {
	@Query(
		value = """
			SELECT new com.ktcloud.travelplanner.travel.repository.TravelListRow(
				travel.id,
				travel.title,
				travel.startDate,
				travel.endDate,
				country.id,
				city.id,
				travel.participantCount,
				travel.updatedAt,
				member.role
			)
			FROM Travel travel
			LEFT JOIN travel.country country
			LEFT JOIN travel.city city
			LEFT JOIN TravelMember member
				ON member.travel = travel
				AND member.user.id = :userId
				AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
			WHERE (travel.owner.id = :userId OR member.id IS NOT NULL)
				AND LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
			ORDER BY travel.updatedAt DESC, travel.id DESC
		""",
		countQuery = """
			SELECT COUNT(travel)
			FROM Travel travel
			LEFT JOIN TravelMember member
				ON member.travel = travel
				AND member.user.id = :userId
				AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
			WHERE (travel.owner.id = :userId OR member.id IS NOT NULL)
				AND LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
		""",
	)
	fun findAccessibleTravels(
		@Param("userId") userId: UUID,
		@Param("keyword") keyword: String,
		pageable: Pageable,
	): Page<TravelListRow>
}
