package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthAuthorizationGrant
import com.ktcloud.travelplanner.auth.client.OAuthProviderClient
import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.exception.ExternalServiceException
import com.ktcloud.travelplanner.user.model.OAuthProvider
import org.springframework.stereotype.Service
import org.springframework.web.util.UriComponentsBuilder
import java.net.URI

@Service
class OAuthLoginService(
	providerClients: List<OAuthProviderClient>,
	private val stateService: OAuthStateService,
	private val userService: OAuthUserService,
	private val exchangeCodeService: OAuthExchangeCodeService,
	private val flowProperties: OAuthFlowProperties,
	private val redirectValidator: FrontendRedirectValidator,
) {
	private val providerClients = providerClients.associateBy(OAuthProviderClient::provider)

	fun createAuthorizationUrl(providerName: String): URI {
		val provider = resolveProvider(providerName)
		val client = resolveClient(provider)
		val frontendRedirectUrl = redirectValidator.validate(flowProperties.frontendRedirectUrl)
		val state = stateService.issue(provider, frontendRedirectUrl.toASCIIString())
		return client.createAuthorizationUrl(state)
	}

	fun completeLogin(providerName: String, authorizationCode: String, state: String): URI {
		val provider = resolveProvider(providerName)
		val client = resolveClient(provider)
		val consumedState = stateService.consume(state, provider)
		val profile = client.fetchUserProfile(
			OAuthAuthorizationGrant(
				authorizationCode = authorizationCode,
				state = state,
			),
		)
		if (profile.provider != provider) {
			throw OAuthProviderException()
		}
		val user = userService.upsert(profile)
		val exchangeCode = exchangeCodeService.issue(requireNotNull(user.id))
		return UriComponentsBuilder.fromUriString(consumedState.frontendRedirectUrl)
			.queryParam("code", exchangeCode)
			.build()
			.encode()
			.toUri()
	}

	private fun resolveProvider(providerName: String): OAuthProvider =
		OAuthProvider.entries.firstOrNull { it.name.equals(providerName, ignoreCase = true) }
			?: throw UnsupportedOAuthProviderException()

	private fun resolveClient(provider: OAuthProvider): OAuthProviderClient =
		providerClients[provider] ?: throw UnsupportedOAuthProviderException()
}

class UnsupportedOAuthProviderException : DomainException(ErrorCode.INVALID_REQUEST)

class OAuthProviderException(
	cause: Throwable? = null,
) : ExternalServiceException(ErrorCode.OAUTH_PROVIDER_ERROR, cause = cause)
