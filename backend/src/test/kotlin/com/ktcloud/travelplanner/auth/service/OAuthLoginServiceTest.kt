package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthProviderClient
import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.user.model.OAuthProvider
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.clearInvocations
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.Duration
import kotlin.test.assertEquals

class OAuthLoginServiceTest {
	private val providerClient = mock(OAuthProviderClient::class.java)
	private val stateService = mock(OAuthStateService::class.java)
	private val userService = mock(OAuthUserService::class.java)
	private val exchangeCodeService = mock(OAuthExchangeCodeService::class.java)
	private val properties = OAuthFlowProperties(
		stateTtl = Duration.ofMinutes(5),
		stateCookieSecure = false,
		exchangeCodeTtl = Duration.ofSeconds(60),
		allowedRedirectOrigins = listOf("http://localhost:3000"),
		frontendRedirectUrl = FRONTEND_REDIRECT_URL,
	)
	private val service: OAuthLoginService

	init {
		`when`(providerClient.provider).thenReturn(OAuthProvider.GOOGLE)
		service = OAuthLoginService(
			providerClients = listOf(providerClient),
			stateService = stateService,
			userService = userService,
			exchangeCodeService = exchangeCodeService,
			flowProperties = properties,
			redirectValidator = FrontendRedirectValidator(properties),
		)
		clearInvocations(providerClient)
	}

	@Test
	fun `access denied consumes state and redirects without provider or user processing`() {
		`when`(stateService.consume(STATE, STATE, OAuthProvider.GOOGLE))
			.thenReturn(ConsumedOAuthState("$FRONTEND_REDIRECT_URL?from=login"))

		val redirectUri = service.completeAuthorization(
			providerName = "google",
			authorizationCode = null,
			authorizationError = "access_denied",
			state = STATE,
			stateCookie = STATE,
		)

		assertEquals(
			"$FRONTEND_REDIRECT_URL?from=login&error=access_denied",
			redirectUri.toASCIIString(),
		)
		verify(stateService).consume(STATE, STATE, OAuthProvider.GOOGLE)
		verifyNoInteractions(providerClient, userService, exchangeCodeService)
	}

	@Test
	fun `unsupported authorization error is rejected without consuming state`() {
		assertThrows<InvalidOAuthAuthorizationResponseException> {
			service.completeAuthorization(
				providerName = "google",
				authorizationCode = null,
				authorizationError = "server_error",
				state = STATE,
				stateCookie = STATE,
			)
		}

		verifyNoInteractions(providerClient, stateService, userService, exchangeCodeService)
	}

	@Test
	fun `authorization code and error together are rejected without consuming state`() {
		assertThrows<InvalidOAuthAuthorizationResponseException> {
			service.completeAuthorization(
				providerName = "google",
				authorizationCode = "provider-code",
				authorizationError = "access_denied",
				state = STATE,
				stateCookie = STATE,
			)
		}

		verifyNoInteractions(providerClient, stateService, userService, exchangeCodeService)
	}

	@Test
	fun `authorization code and error both missing are rejected without consuming state`() {
		assertThrows<InvalidOAuthAuthorizationResponseException> {
			service.completeAuthorization(
				providerName = "google",
				authorizationCode = null,
				authorizationError = null,
				state = STATE,
				stateCookie = STATE,
			)
		}

		verifyNoInteractions(providerClient, stateService, userService, exchangeCodeService)
	}

	companion object {
		private const val STATE = "oauth-state"
		private const val FRONTEND_REDIRECT_URL = "http://localhost:3000/auth/callback"
	}
}
