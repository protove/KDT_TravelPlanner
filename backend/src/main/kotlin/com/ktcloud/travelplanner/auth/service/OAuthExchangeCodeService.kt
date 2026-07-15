package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.auth.repository.OneTimeTokenStore
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import java.util.UUID

@Service
class OAuthExchangeCodeService(
	private val tokenStore: OneTimeTokenStore,
	private val tokenGenerator: OpaqueTokenGenerator,
	private val properties: OAuthFlowProperties,
	private val userRepository: UserRepository,
	private val jwtTokenService: JwtTokenService,
) {
	fun issue(userId: UUID): String {
		val code = tokenGenerator.generate()
		tokenStore.put(
			EXCHANGE_CODE_NAMESPACE,
			code,
			userId.toString(),
			properties.exchangeCodeTtl,
		)
		return code
	}

	fun exchange(code: String): IssuedAccessToken {
		val userId = tokenStore.consume(EXCHANGE_CODE_NAMESPACE, code)
			?.let(::parseUserId)
			?: throw InvalidAuthorizationCodeException()
		if (!userRepository.existsById(userId)) {
			throw InvalidAuthorizationCodeException()
		}
		return jwtTokenService.issueAccessToken(userId)
	}

	private fun parseUserId(value: String): UUID = try {
		UUID.fromString(value)
	} catch (exception: IllegalArgumentException) {
		throw InvalidAuthorizationCodeException()
	}

	companion object {
		internal const val EXCHANGE_CODE_NAMESPACE = "oauth-exchange-code"
	}
}

class InvalidAuthorizationCodeException : DomainException(ErrorCode.INVALID_AUTHORIZATION_CODE)
