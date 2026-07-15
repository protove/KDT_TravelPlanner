package com.ktcloud.travelplanner.user.repository

import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.springframework.data.jpa.repository.JpaRepository
import java.util.UUID

interface UserRepository : JpaRepository<User, UUID> {
	fun findByProviderAndProviderUserId(
		provider: OAuthProvider,
		providerUserId: String,
	): User?

	fun findByNickname(nickname: String): User?

	fun existsByNickname(nickname: String): Boolean
}
