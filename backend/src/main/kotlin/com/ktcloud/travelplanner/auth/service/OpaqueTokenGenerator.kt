package com.ktcloud.travelplanner.auth.service

import org.springframework.stereotype.Component
import java.security.SecureRandom
import java.util.Base64

fun interface OpaqueTokenGenerator {
	fun generate(): String
}

@Component
class SecureOpaqueTokenGenerator : OpaqueTokenGenerator {
	private val secureRandom = SecureRandom()

	override fun generate(): String {
		val bytes = ByteArray(TOKEN_BYTES)
		secureRandom.nextBytes(bytes)
		return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
	}

	companion object {
		private const val TOKEN_BYTES = 32
	}
}
