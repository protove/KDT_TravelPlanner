package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import com.ktcloud.travelplanner.auth.repository.RefreshTokenHasher
import com.ktcloud.travelplanner.auth.repository.RefreshTokenRotationResult
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
	private val tokenGenerator = mock(OpaqueTokenGenerator::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val jwtTokenService = mock(JwtTokenService::class.java)
	private val properties = RefreshTokenProperties(
		ttl = Duration.ofDays(30),
		cookieSecure = false,
		cookieSameSite = "Lax",
	)
	private val service = RefreshTokenService(
		tokenStore = tokenStore,
		tokenGenerator = tokenGenerator,
		properties = properties,
		userRepository = userRepository,
		jwtTokenService = jwtTokenService,
	)

	@Test
	fun `issues opaque refresh token family with user id and configured TTL`() {
		`when`(jwtTokenService.parseUserId(ACCESS_TOKEN.value)).thenReturn(TestFixtures.USER_ID)
		`when`(tokenGenerator.generate()).thenReturn(FAMILY_ID, REFRESH_TOKEN)

		val issued = service.issueForAccessToken(ACCESS_TOKEN)

		assertEquals(REFRESH_TOKEN, issued.value)
		verify(tokenStore).save(
			REFRESH_TOKEN,
			TestFixtures.USER_ID,
			FAMILY_ID,
			Duration.ofDays(30),
		)
	}

	@Test
	fun `rotates refresh token and issues access token for active user`() {
		val expectedAccessToken = IssuedAccessToken(
			"new-access-token",
			TestFixtures.FIXED_INSTANT.plusSeconds(1800),
		)
		`when`(tokenGenerator.generate()).thenReturn(ROTATED_REFRESH_TOKEN)
		`when`(tokenStore.rotate(REFRESH_TOKEN, ROTATED_REFRESH_TOKEN))
			.thenReturn(RefreshTokenRotationResult.Rotated(TestFixtures.USER_ID.toString()))
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(true)
		`when`(jwtTokenService.issueAccessToken(TestFixtures.USER_ID)).thenReturn(expectedAccessToken)

		val refreshed = service.refresh(REFRESH_TOKEN)

		assertEquals(expectedAccessToken, refreshed.accessToken)
		assertEquals(ROTATED_REFRESH_TOKEN, refreshed.refreshToken.value)
	}

	@Test
	fun `rejects missing malformed invalid and reused tokens`() {
		assertThrows<InvalidRefreshTokenException> { service.refresh(null) }
		assertThrows<InvalidRefreshTokenException> { service.refresh("too-short") }
		verifyNoInteractions(tokenStore)

		`when`(tokenGenerator.generate()).thenReturn(ROTATED_REFRESH_TOKEN)
		`when`(tokenStore.rotate(REFRESH_TOKEN, ROTATED_REFRESH_TOKEN))
			.thenReturn(RefreshTokenRotationResult.Invalid)
			.thenReturn(RefreshTokenRotationResult.Reused)

		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }
		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }
		verifyNoInteractions(userRepository, jwtTokenService)
	}

	@Test
	fun `revokes rotated family when stored user is missing`() {
		`when`(tokenGenerator.generate()).thenReturn(ROTATED_REFRESH_TOKEN)
		`when`(tokenStore.rotate(REFRESH_TOKEN, ROTATED_REFRESH_TOKEN))
			.thenReturn(RefreshTokenRotationResult.Rotated(TestFixtures.USER_ID.toString()))
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(false)

		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }

		verify(tokenStore).revokeFamily(ROTATED_REFRESH_TOKEN)
		verify(jwtTokenService, never()).issueAccessToken(TestFixtures.USER_ID)
	}

	@Test
	fun `revokes rotated family when stored user id is malformed`() {
		`when`(tokenGenerator.generate()).thenReturn(ROTATED_REFRESH_TOKEN)
		`when`(tokenStore.rotate(REFRESH_TOKEN, ROTATED_REFRESH_TOKEN))
			.thenReturn(RefreshTokenRotationResult.Rotated("not-a-uuid"))

		assertThrows<InvalidRefreshTokenException> { service.refresh(REFRESH_TOKEN) }

		verify(tokenStore).revokeFamily(ROTATED_REFRESH_TOKEN)
		verifyNoInteractions(userRepository, jwtTokenService)
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
	fun `revokes valid token family and ignores missing or malformed token idempotently`() {
		service.revoke(REFRESH_TOKEN)
		service.revoke(null)
		service.revoke("too-short")

		verify(tokenStore).revokeFamily(REFRESH_TOKEN)
		verify(tokenStore, never()).revokeFamily("too-short")
	}

	companion object {
		private const val FAMILY_ID = "refresh-token-family"
		private val REFRESH_TOKEN = "r".repeat(43)
		private val ROTATED_REFRESH_TOKEN = "n".repeat(43)
		private val ACCESS_TOKEN = IssuedAccessToken(
			value = "issued-access-token",
			expiresAt = TestFixtures.FIXED_INSTANT.plusSeconds(1800),
		)
	}
}
