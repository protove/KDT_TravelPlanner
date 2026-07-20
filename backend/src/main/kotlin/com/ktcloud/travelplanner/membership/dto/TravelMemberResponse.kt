package com.ktcloud.travelplanner.membership.dto

import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.user.model.User
import java.util.UUID

data class TravelMemberResponse(
	val userId: UUID,
	val nickname: String?,
	val profileImageUrl: String?,
	val role: TravelPermission,
	val isOwner: Boolean,
) {
	companion object {
		fun fromOwner(owner: User): TravelMemberResponse = TravelMemberResponse(
			userId = requireNotNull(owner.id),
			nickname = owner.nickname,
			profileImageUrl = owner.profileImageUrl,
			role = TravelPermission.OWNER,
			isOwner = true,
		)

		fun fromMember(member: TravelMember): TravelMemberResponse = TravelMemberResponse(
			userId = requireNotNull(member.user.id),
			nickname = member.user.nickname,
			profileImageUrl = member.user.profileImageUrl,
			role = TravelPermission.valueOf(member.role.name),
			isOwner = false,
		)
	}
}
