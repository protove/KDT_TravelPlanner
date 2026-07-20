package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.auth.repository.OneTimeTokenStore
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import java.time.Duration
import kotlin.test.assertEquals

class OAuthExchangeCodeServiceTest {
	private val tokenStore = mock(OneTimeTokenStore::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val jwtTokenService = mock(JwtTokenService::class.java)
	private val properties = OAuthFlowProperties(
		stateTtl = Duration.ofMinutes(5),
		exchangeCodeTtl = Duration.ofSeconds(60),
		allowedRedirectOrigins = listOf("http://localhost:3000"),
		frontendRedirectUrl = "http://localhost:3000/auth/callback",
	)
	private val service = OAuthExchangeCodeService(
		tokenStore = tokenStore,
		tokenGenerator = OpaqueTokenGenerator { CODE },
		properties = properties,
		userRepository = userRepository,
		jwtTokenService = jwtTokenService,
	)

	@Test
	fun `issues one-time code with user id and 60 second TTL`() {
		val code = service.issue(TestFixtures.USER_ID)

		assertEquals(CODE, code)
		verify(tokenStore).put(
			OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE,
			CODE,
			TestFixtures.USER_ID.toString(),
			Duration.ofSeconds(60),
		)
	}

	@Test
	fun `consumes code once and issues access token for active user`() {
		val expected = IssuedAccessToken("access-token", TestFixtures.FIXED_INSTANT.plusSeconds(1800))
		`when`(tokenStore.consume(OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE, CODE))
			.thenReturn(TestFixtures.USER_ID.toString())
			.thenReturn(null)
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(true)
		`when`(jwtTokenService.issueAccessToken(TestFixtures.USER_ID)).thenReturn(expected)

		assertEquals(expected, service.exchange(CODE))
		assertThrows<InvalidAuthorizationCodeException> { service.exchange(CODE) }
	}

	@Test
	fun `rejects expired unknown or malformed code`() {
		`when`(tokenStore.consume(OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE, "expired"))
			.thenReturn(null)
		`when`(tokenStore.consume(OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE, "malformed"))
			.thenReturn("not-a-uuid")

		assertThrows<InvalidAuthorizationCodeException> { service.exchange("expired") }
		assertThrows<InvalidAuthorizationCodeException> { service.exchange("malformed") }
	}

	@Test
	fun `rejects code for deleted or absent user`() {
		`when`(tokenStore.consume(OAuthExchangeCodeService.EXCHANGE_CODE_NAMESPACE, CODE))
			.thenReturn(TestFixtures.USER_ID.toString())
		`when`(userRepository.existsById(TestFixtures.USER_ID)).thenReturn(false)

		assertThrows<InvalidAuthorizationCodeException> { service.exchange(CODE) }
	}

	companion object {
		private const val CODE = "deterministic-exchange-code"
	}
}
