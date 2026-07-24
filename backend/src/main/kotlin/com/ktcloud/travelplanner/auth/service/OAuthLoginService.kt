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

data class OAuthAuthorizationRedirect(
	val location: URI,
	val state: String,
)

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

	fun createAuthorizationRedirect(providerName: String): OAuthAuthorizationRedirect {
		val provider = resolveProvider(providerName)
		val client = resolveClient(provider)
		val frontendRedirectUrl = redirectValidator.validate(flowProperties.frontendRedirectUrl)
		val state = stateService.issue(provider, frontendRedirectUrl.toASCIIString())
		return OAuthAuthorizationRedirect(
			location = client.createAuthorizationUrl(state),
			state = state,
		)
	}

	fun completeAuthorization(
		providerName: String,
		authorizationCode: String?,
		authorizationError: String?,
		state: String,
		stateCookie: String?,
	): URI {
		val provider = resolveProvider(providerName)
		return when {
			!authorizationCode.isNullOrBlank() && authorizationError == null ->
				completeApprovedAuthorization(provider, authorizationCode, state, stateCookie)

			authorizationCode == null && authorizationError == ACCESS_DENIED_ERROR ->
				completeDeniedAuthorization(provider, state, stateCookie)

			else -> throw InvalidOAuthAuthorizationResponseException()
		}
	}

	private fun completeApprovedAuthorization(
		provider: OAuthProvider,
		authorizationCode: String,
		state: String,
		stateCookie: String?,
	): URI {
		val client = resolveClient(provider)
		val consumedState = stateService.consume(state, stateCookie, provider)
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

	private fun completeDeniedAuthorization(
		provider: OAuthProvider,
		state: String,
		stateCookie: String?,
	): URI {
		val consumedState = stateService.consume(state, stateCookie, provider)
		return UriComponentsBuilder.fromUriString(consumedState.frontendRedirectUrl)
			.queryParam(ERROR_QUERY_PARAMETER, ACCESS_DENIED_ERROR)
			.build()
			.encode()
			.toUri()
	}

	private fun resolveProvider(providerName: String): OAuthProvider =
		OAuthProvider.entries.firstOrNull { it.name.equals(providerName, ignoreCase = true) }
			?: throw UnsupportedOAuthProviderException()

	private fun resolveClient(provider: OAuthProvider): OAuthProviderClient =
		providerClients[provider] ?: throw UnsupportedOAuthProviderException()

	companion object {
		private const val ERROR_QUERY_PARAMETER = "error"
		private const val ACCESS_DENIED_ERROR = "access_denied"
	}
}

class UnsupportedOAuthProviderException : DomainException(ErrorCode.INVALID_REQUEST)

class InvalidOAuthAuthorizationResponseException : DomainException(
	ErrorCode.INVALID_REQUEST,
	"OAuth 인증 응답이 올바르지 않습니다.",
)

class OAuthProviderException(
	cause: Throwable? = null,
) : ExternalServiceException(ErrorCode.OAUTH_PROVIDER_ERROR, cause = cause)
