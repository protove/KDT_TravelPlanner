package com.ktcloud.travelplanner.membership.dto

import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.model.TravelMember
import java.time.Instant
import java.util.UUID

data class TravelInvitationStatusResponse(
	val invitationId: UUID,
	val status: InvitationStatus,
	val respondedAt: Instant,
) {
	companion object {
		fun from(member: TravelMember): TravelInvitationStatusResponse = TravelInvitationStatusResponse(
			invitationId = member.id,
			status = member.status,
			respondedAt = requireNotNull(member.respondedAt),
		)
	}
}
