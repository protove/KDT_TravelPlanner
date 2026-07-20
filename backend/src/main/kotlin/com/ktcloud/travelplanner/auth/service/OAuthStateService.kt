package com.ktcloud.travelplanner.auth.service

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.auth.repository.OneTimeTokenStore
import com.ktcloud.travelplanner.user.model.OAuthProvider
import org.springframework.stereotype.Service
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

data class ConsumedOAuthState(
	val frontendRedirectUrl: String,
)

private data class OAuthStatePayload(
	val provider: OAuthProvider,
	val frontendRedirectUrl: String,
)

@Service
class OAuthStateService(
	private val tokenStore: OneTimeTokenStore,
	private val tokenGenerator: OpaqueTokenGenerator,
	private val redirectValidator: FrontendRedirectValidator,
	private val properties: OAuthFlowProperties,
	private val objectMapper: ObjectMapper,
) {
	fun issue(provider: OAuthProvider, frontendRedirectUrl: String): String {
		val validatedRedirectUrl = redirectValidator.validate(frontendRedirectUrl).toASCIIString()
		val state = tokenGenerator.generate()
		val payload = objectMapper.writeValueAsString(
			OAuthStatePayload(provider, validatedRedirectUrl),
		)
		tokenStore.put(STATE_NAMESPACE, state, payload, properties.stateTtl)
		return state
	}

	fun consume(
		state: String,
		stateCookie: String?,
		expectedProvider: OAuthProvider,
	): ConsumedOAuthState {
		if (!matchesBrowserState(state, stateCookie)) {
			throw InvalidOAuthStateException()
		}
		val serializedPayload = tokenStore.consume(STATE_NAMESPACE, state)
			?: throw InvalidOAuthStateException()
		val payload = try {
			objectMapper.readValue(serializedPayload, OAuthStatePayload::class.java)
		} catch (exception: Exception) {
			throw InvalidOAuthStateException()
		}

		if (payload.provider != expectedProvider) {
			throw InvalidOAuthStateException()
		}
		redirectValidator.validate(payload.frontendRedirectUrl)
		return ConsumedOAuthState(payload.frontendRedirectUrl)
	}

	private fun matchesBrowserState(state: String, stateCookie: String?): Boolean {
		if (stateCookie == null) {
			return false
		}
		return MessageDigest.isEqual(
			state.toByteArray(StandardCharsets.UTF_8),
			stateCookie.toByteArray(StandardCharsets.UTF_8),
		)
	}

	companion object {
		internal const val STATE_NAMESPACE = "oauth-state"
	}
}
