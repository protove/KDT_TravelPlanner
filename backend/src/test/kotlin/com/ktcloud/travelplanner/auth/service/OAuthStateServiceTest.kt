package com.ktcloud.travelplanner.auth.service

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.auth.repository.OneTimeTokenStore
import com.ktcloud.travelplanner.user.model.OAuthProvider
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Duration
import kotlin.test.assertEquals

class OAuthStateServiceTest {
	private val objectMapper = jacksonObjectMapper()
	private val tokenStore = InMemoryOneTimeTokenStore()
	private val properties = properties()
	private val service = OAuthStateService(
		tokenStore = tokenStore,
		tokenGenerator = OpaqueTokenGenerator { STATE },
		redirectValidator = FrontendRedirectValidator(properties),
		properties = properties,
		objectMapper = objectMapper,
	)

	@Test
	fun `issues state with provider redirect URL and configured TTL`() {
		val state = service.issue(OAuthProvider.GOOGLE, REDIRECT_URL)

		assertEquals(STATE, state)
		assertEquals(Duration.ofMinutes(5), tokenStore.lastTtl)
		val payload = objectMapper.readTree(
			tokenStore.peek(OAuthStateService.STATE_NAMESPACE, STATE),
		)
		assertEquals("GOOGLE", payload["provider"].asText())
		assertEquals(REDIRECT_URL, payload["frontendRedirectUrl"].asText())
	}

	@Test
	fun `consumes state once and returns validated redirect URL`() {
		tokenStore.seed(
			OAuthStateService.STATE_NAMESPACE,
			STATE,
			payload(OAuthProvider.NAVER, REDIRECT_URL),
		)

		val consumed = service.consume(STATE, OAuthProvider.NAVER)

		assertEquals(REDIRECT_URL, consumed.frontendRedirectUrl)
		assertThrows<InvalidOAuthStateException> {
			service.consume(STATE, OAuthProvider.NAVER)
		}
	}

	@Test
	fun `rejects expired or unknown state`() {
		assertThrows<InvalidOAuthStateException> {
			service.consume(STATE, OAuthProvider.GOOGLE)
		}
	}

	@Test
	fun `rejects provider mismatch and consumes the state`() {
		tokenStore.seed(
			OAuthStateService.STATE_NAMESPACE,
			STATE,
			payload(OAuthProvider.GOOGLE, REDIRECT_URL),
		)

		assertThrows<InvalidOAuthStateException> {
			service.consume(STATE, OAuthProvider.NAVER)
		}
		assertThrows<InvalidOAuthStateException> {
			service.consume(STATE, OAuthProvider.GOOGLE)
		}
	}

	@Test
	fun `rejects redirect URL outside configured frontend origins`() {
		assertThrows<InvalidOAuthStateException> {
			service.issue(OAuthProvider.GOOGLE, "https://attacker.example/callback")
		}
	}

	@Test
	fun `accepts paths on configured origin but rejects user info and fragments`() {
		assertEquals(
			"http://localhost:3000/auth/callback?from=login",
			FrontendRedirectValidator(properties).validate(
				"http://localhost:3000/auth/callback?from=login",
			).toASCIIString(),
		)
		assertThrows<InvalidOAuthStateException> {
			FrontendRedirectValidator(properties).validate("http://user@localhost:3000/auth/callback")
		}
		assertThrows<InvalidOAuthStateException> {
			FrontendRedirectValidator(properties).validate("http://localhost:3000/auth/callback#token")
		}
	}

	private fun payload(provider: OAuthProvider, redirectUrl: String): String =
		"""{"provider":"${provider.name}","frontendRedirectUrl":"$redirectUrl"}"""

	private fun properties(): OAuthFlowProperties = OAuthFlowProperties(
		stateTtl = Duration.ofMinutes(5),
		exchangeCodeTtl = Duration.ofSeconds(60),
		allowedRedirectOrigins = listOf("http://localhost:3000"),
	)

	companion object {
		private const val STATE = "deterministic-oauth-state"
		private const val REDIRECT_URL = "http://localhost:3000/auth/callback"
	}
}

private class InMemoryOneTimeTokenStore : OneTimeTokenStore {
	private val values = mutableMapOf<Pair<String, String>, String>()
	var lastTtl: Duration? = null
		private set

	override fun put(namespace: String, token: String, value: String, ttl: Duration) {
		values[namespace to token] = value
		lastTtl = ttl
	}

	override fun consume(namespace: String, token: String): String? =
		values.remove(namespace to token)

	fun seed(namespace: String, token: String, value: String) {
		values[namespace to token] = value
	}

	fun peek(namespace: String, token: String): String? = values[namespace to token]
}
