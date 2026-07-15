package com.ktcloud.travelplanner.membership.repository

import com.ktcloud.travelplanner.membership.model.TravelMember
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID

interface TravelMemberRepository : JpaRepository<TravelMember, UUID> {
	@Query(
		"""
		SELECT CASE WHEN COUNT(member) > 0 THEN TRUE ELSE FALSE END
		FROM TravelMember member
		WHERE member.travel.id = :travelId AND member.user.id = :userId
		""",
	)
	fun existsByTravelAndUser(
		@Param("travelId") travelId: UUID,
		@Param("userId") userId: UUID,
	): Boolean

	@Query(
		"""
		SELECT CASE WHEN COUNT(member) > 0 THEN TRUE ELSE FALSE END
		FROM TravelMember member
		WHERE member.travel.id = :travelId
			AND member.user.id = :userId
			AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
			AND member.role = com.ktcloud.travelplanner.membership.model.TravelRole.READ_WRITE
		""",
	)
	fun existsAcceptedReadWriteMember(
		@Param("travelId") travelId: UUID,
		@Param("userId") userId: UUID,
	): Boolean
}
