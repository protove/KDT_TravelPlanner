package com.ktcloud.travelplanner.global.security

import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import kotlin.test.assertEquals

class JwtTokenServiceTest {
	private val issuedAt = Instant.parse("2026-07-15T00:00:00Z")
	private val userId = UUID.fromString("11111111-2222-3333-4444-555555555555")

	@Test
	fun `issues access token with user id and configured expiration`() {
		val service = serviceAt(issuedAt)

		val token = service.issueAccessToken(userId)

		assertEquals(issuedAt.plus(Duration.ofMinutes(30)), token.expiresAt)
		assertEquals(userId, service.parseUserId(token.value))
	}

	@Test
	fun `rejects expired access token`() {
		val token = serviceAt(issuedAt).issueAccessToken(userId)
		val expiredService = serviceAt(token.expiresAt.plusSeconds(1))

		assertThrows<InvalidAccessTokenException> {
			expiredService.parseUserId(token.value)
		}
	}

	@Test
	fun `rejects token with tampered signature`() {
		val service = serviceAt(issuedAt)
		val token = service.issueAccessToken(userId).value
		val replacement = if (token.last() == 'a') 'b' else 'a'
		val tampered = token.dropLast(1) + replacement

		assertThrows<InvalidAccessTokenException> {
			service.parseUserId(tampered)
		}
	}

	@Test
	fun `rejects token signed by another secret`() {
		val token = serviceAt(issuedAt).issueAccessToken(userId)
		val otherService = JwtTokenService(
			properties("another-test-jwt-secret-with-32-bytes"),
			Clock.fixed(issuedAt, ZoneOffset.UTC),
		)

		assertThrows<InvalidAccessTokenException> {
			otherService.parseUserId(token.value)
		}
	}

	@Test
	fun `requires a secret of at least 32 bytes`() {
		assertThrows<IllegalArgumentException> {
			properties("too-short")
		}
	}

	private fun serviceAt(now: Instant): JwtTokenService = JwtTokenService(
		properties(TEST_SECRET),
		Clock.fixed(now, ZoneOffset.UTC),
	)

	private fun properties(secret: String): JwtProperties = JwtProperties(
		issuer = "travel-planner-backend",
		accessTokenTtl = Duration.ofMinutes(30),
		secret = secret,
	)

	companion object {
		private const val TEST_SECRET = "test-jwt-secret-with-at-least-32-bytes"
	}
}
