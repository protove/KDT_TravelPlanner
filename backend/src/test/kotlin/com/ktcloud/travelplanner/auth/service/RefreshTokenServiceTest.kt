package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import com.ktcloud.travelplanner.auth.repository.RefreshTokenHasher
import com.ktcloud.travelplanner.auth.repository.RefreshTokenStore
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.Duration
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class RefreshTokenServiceTest {
	private val tokenStore = mock(RefreshTokenStore::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val jwtTokenService = mock(JwtTokenService::class.java)
	private val properties = RefreshTokenProperties(
		ttl = Duration.ofDays(30),
		cookieSecure = false,
		cookieSameSite = "Lax",
	)
	private val service = RefreshTokenService(
		tokenStore = tokenStore,
		tokenGenerator = OpaqueTokenGenerator { REFRESH_TOKEN },
		properties = properties,
		userRepository = userRepository,
		jwtTokenService = jwtTokenService,
	)

	@Test
	fun `issues opaque refresh token with user id and configured TTL`() {
		`when`(jwtTokenService.parseUserId(ACCESS_TOKEN.value)).thenReturn(TestFixtures.USER_ID)

		val issued = service.issueForAccessToken(ACCESS_TOKEN)

		assertEquals(REFRESH_TOKEN, issued.value)
		verify(tokenStore).save(REFRESH_TOKEN, TestFixtures.USER_ID, Duration.ofDays(30))
	}

	@Test
	fun `refreshes access token for stored active user`() {
		val expected = IssuedAccessToken("new-access-token", TestFixtures.FIXED_INSTANT.plusSeconds(1800))
		`when`(tokenStore.findUserId(REFRESH_TOKEN)).thenReturn(TestFixtures.USER_ID.toString())
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(true)
		`when`(jwtTokenService.issueAccessToken(TestFixtures.USER_ID)).thenReturn(expected)

		assertEquals(expected, service.refresh(REFRESH_TOKEN))
	}

	@Test
	fun `rejects missing malformed expired mismatched and deleted user tokens`() {
		assertThrows<InvalidRefreshTokenException> { service.refresh(null) }
		assertThrows<InvalidRefreshTokenException> { service.refresh("too-short") }
		verifyNoInteractions(tokenStore)

		`when`(tokenStore.findUserId(REFRESH_TOKEN))
			.thenReturn(null)
			.thenReturn("not-a-uuid")
			.thenReturn(TestFixtures.USER_ID.toString())
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(false)

		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }
		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }
		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }
	}

	@Test
	fun `hashes refresh token deterministically without retaining raw value`() {
		val tokenHasher = RefreshTokenHasher()

		val hash = tokenHasher.hash(REFRESH_TOKEN)

		assertEquals(64, hash.length)
		assertEquals(hash, tokenHasher.hash(REFRESH_TOKEN))
		assertNotEquals(REFRESH_TOKEN, hash)
		assertNotEquals(hash, tokenHasher.hash("a".repeat(43)))
	}

	@Test
	fun `revokes valid token and ignores missing or malformed token idempotently`() {
		service.revoke(REFRESH_TOKEN)
		service.revoke(null)
		service.revoke("too-short")

		verify(tokenStore).delete(REFRESH_TOKEN)
		verify(tokenStore, never()).delete("too-short")
	}

	companion object {
		private val REFRESH_TOKEN = "r".repeat(43)
		private val ACCESS_TOKEN = IssuedAccessToken(
			value = "issued-access-token",
			expiresAt = TestFixtures.FIXED_INSTANT.plusSeconds(1800),
		)
	}
}
