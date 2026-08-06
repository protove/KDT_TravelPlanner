package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class OAuthUserService(
	private val userRepository: UserRepository,
) {
	@Transactional
	fun upsert(profile: OAuthUserProfile): User {
		val existingUser = userRepository.findByProviderAndProviderUserId(
			profile.provider,
			profile.providerUserId,
		)
		if (existingUser != null) {
			existingUser.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			return existingUser
		}

		return userRepository.save(
			User(
				provider = profile.provider,
				providerUserId = profile.providerUserId,
				email = profile.email,
				name = profile.name,
			).also {
				it.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			},
		)
	}
}
