package com.ktcloud.travelplanner.auth.client

import com.ktcloud.travelplanner.user.model.OAuthProvider
import java.net.URI

data class OAuthUserProfile(
	val provider: OAuthProvider,
	val providerUserId: String,
	val email: String?,
	val name: String?,
	val profileImageUrl: String?,
)

interface OAuthProviderClient {
	val provider: OAuthProvider

	fun createAuthorizationUrl(state: String): URI

	fun fetchUserProfile(authorizationCode: String): OAuthUserProfile
}
