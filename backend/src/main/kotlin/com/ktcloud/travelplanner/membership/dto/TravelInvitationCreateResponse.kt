package com.ktcloud.travelplanner.membership.dto

import com.ktcloud.travelplanner.membership.model.TravelMember
import java.util.UUID

data class TravelInvitationCreateResponse(
	val invitationId: UUID,
) {
	companion object {
		fun from(member: TravelMember): TravelInvitationCreateResponse =
			TravelInvitationCreateResponse(member.id)
	}
}
