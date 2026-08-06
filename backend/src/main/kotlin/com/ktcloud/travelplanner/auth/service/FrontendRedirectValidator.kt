package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.config.OAuthFlowProperties
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import org.springframework.stereotype.Component
import java.net.URI

@Component
class FrontendRedirectValidator(
	private val properties: OAuthFlowProperties,
) {
	fun validate(redirectUrl: String): URI {
		val redirectUri = try {
			URI.create(redirectUrl)
		} catch (exception: IllegalArgumentException) {
			throw InvalidOAuthStateException()
		}

		if (
			!redirectUri.isAbsolute ||
			redirectUri.host == null ||
			redirectUri.userInfo != null ||
			redirectUri.fragment != null ||
			OAuthFlowProperties.normalizeOrigin(redirectUri) !in properties.parsedAllowedRedirectOrigins
		) {
			throw InvalidOAuthStateException()
		}
		return redirectUri
	}
}

class InvalidOAuthStateException : DomainException(ErrorCode.INVALID_OAUTH_STATE)
