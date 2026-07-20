package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.RefreshTokenProperties
import com.ktcloud.travelplanner.auth.repository.RefreshTokenRotationResult
import com.ktcloud.travelplanner.auth.repository.RefreshTokenStore
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.security.IssuedAccessToken
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import java.util.UUID

data class IssuedRefreshToken(
	val value: String,
)

data class RefreshedTokens(
	val accessToken: IssuedAccessToken,
	val refreshToken: IssuedRefreshToken,
)

@Service
class RefreshTokenService(
	private val tokenStore: RefreshTokenStore,
	private val tokenGenerator: OpaqueTokenGenerator,
	private val properties: RefreshTokenProperties,
	private val userRepository: UserRepository,
	private val jwtTokenService: JwtTokenService,
) {
	fun issueForAccessToken(accessToken: IssuedAccessToken): IssuedRefreshToken {
		val userId = jwtTokenService.parseUserId(accessToken.value)
		val familyId = tokenGenerator.generate()
		val refreshToken = tokenGenerator.generate()
		tokenStore.save(refreshToken, userId, familyId, properties.ttl)
		return IssuedRefreshToken(refreshToken)
	}

	fun refresh(refreshToken: String?): RefreshedTokens {
		if (!isValidFormat(refreshToken)) {
			throw InvalidRefreshTokenException()
		}
		val rotatedToken = tokenGenerator.generate()
		val userId = when (val result = tokenStore.rotate(requireNotNull(refreshToken), rotatedToken)) {
			is RefreshTokenRotationResult.Rotated -> try {
				parseUserId(result.userId)
			} catch (exception: InvalidRefreshTokenException) {
				tokenStore.revokeFamily(rotatedToken)
				throw exception
			}
			RefreshTokenRotationResult.Reused,
			RefreshTokenRotationResult.Invalid,
			-> throw InvalidRefreshTokenException()
		}
		if (!userRepository.existsById(userId)) {
			tokenStore.revokeFamily(rotatedToken)
			throw InvalidRefreshTokenException()
		}
		val accessToken = try {
			jwtTokenService.issueAccessToken(userId)
		} catch (exception: Exception) {
			tokenStore.revokeFamily(rotatedToken)
			throw exception
		}
		return RefreshedTokens(
			accessToken = accessToken,
			refreshToken = IssuedRefreshToken(rotatedToken),
		)
	}

	fun revoke(refreshToken: String?) {
		if (isValidFormat(refreshToken)) {
			tokenStore.revokeFamily(requireNotNull(refreshToken))
		}
	}

	private fun isValidFormat(refreshToken: String?): Boolean =
		refreshToken != null && REFRESH_TOKEN_PATTERN.matches(refreshToken)

	private fun parseUserId(value: String): UUID = try {
		UUID.fromString(value)
	} catch (exception: IllegalArgumentException) {
		throw InvalidRefreshTokenException()
	}

	companion object {
		private val REFRESH_TOKEN_PATTERN = Regex("^[A-Za-z0-9_-]{43}$")
	}
}

class InvalidRefreshTokenException : DomainException(ErrorCode.INVALID_REFRESH_TOKEN)
