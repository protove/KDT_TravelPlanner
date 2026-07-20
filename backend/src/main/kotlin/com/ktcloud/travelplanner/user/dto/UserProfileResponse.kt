package com.ktcloud.travelplanner.user.dto

import com.ktcloud.travelplanner.user.model.Gender
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import java.util.UUID

data class UserProfileResponse(
	val userId: UUID,
	val provider: OAuthProvider,
	val email: String?,
	val name: String?,
	val nickname: String?,
	val profileImageUrl: String?,
	val gender: Gender?,
	val birthYear: Int?,
	val isProfileCompleted: Boolean,
) {
	companion object {
		fun from(user: User): UserProfileResponse = UserProfileResponse(
			userId = requireNotNull(user.id),
			provider = user.provider,
			email = user.email,
			name = user.name,
			nickname = user.nickname,
			profileImageUrl = user.profileImageUrl,
			gender = user.gender,
			birthYear = user.birthYear?.toInt(),
			isProfileCompleted = user.isProfileCompleted,
		)
	}
}
