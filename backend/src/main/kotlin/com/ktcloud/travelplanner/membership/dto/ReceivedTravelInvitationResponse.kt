package com.ktcloud.travelplanner.membership.dto

import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

data class ReceivedTravelInvitationResponse(
	val invitationId: UUID,
	val status: InvitationStatus,
	val role: TravelRole,
	val invitedAt: Instant,
	val travel: InvitedTravelResponse,
	val inviter: TravelInviterResponse,
) {
	companion object {
		fun from(member: TravelMember): ReceivedTravelInvitationResponse {
			val travel = member.travel
			val inviter = travel.owner
			return ReceivedTravelInvitationResponse(
				invitationId = member.id,
				status = member.status,
				role = member.role,
				invitedAt = member.invitedAt,
				travel = InvitedTravelResponse(
					travelId = travel.id,
					title = travel.title,
					startDate = travel.startDate,
					endDate = travel.endDate,
				),
				inviter = TravelInviterResponse(
					userId = requireNotNull(inviter.id),
					nickname = inviter.nickname,
					profileImageUrl = inviter.profileImageUrl,
				),
			)
		}
	}
}

data class InvitedTravelResponse(
	val travelId: UUID,
	val title: String,
	val startDate: LocalDate,
	val endDate: LocalDate,
)

data class TravelInviterResponse(
	val userId: UUID,
	val nickname: String?,
	val profileImageUrl: String?,
)
