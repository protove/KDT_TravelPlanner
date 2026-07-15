package com.ktcloud.travelplanner.global.security

import java.security.Principal
import java.util.UUID

data class AuthenticatedUserPrincipal(
	val userId: UUID,
) : Principal {
	override fun getName(): String = userId.toString()
}
