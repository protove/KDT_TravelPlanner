package com.ktcloud.travelplanner.global.security

import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.springframework.security.authentication.BadCredentialsException
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken
import org.springframework.security.core.context.SecurityContextHolder
import org.springframework.security.web.authentication.WebAuthenticationDetailsSource
import org.springframework.web.filter.OncePerRequestFilter

class JwtAuthenticationFilter(
	private val jwtTokenService: JwtTokenService,
	private val userRepository: UserRepository,
	private val apiSecurityErrorHandler: ApiSecurityErrorHandler,
) : OncePerRequestFilter() {
	override fun doFilterInternal(
		request: HttpServletRequest,
		response: HttpServletResponse,
		filterChain: FilterChain,
	) {
		val authorization = request.getHeader(AUTHORIZATION_HEADER)
		if (authorization == null) {
			filterChain.doFilter(request, response)
			return
		}

		try {
			val token = extractBearerToken(authorization)
			val userId = jwtTokenService.parseUserId(token)
			if (!userRepository.existsById(userId)) {
				throw InvalidAccessTokenException()
			}

			val principal = AuthenticatedUserPrincipal(userId)
			val authentication = UsernamePasswordAuthenticationToken.authenticated(
				principal,
				null,
				emptyList(),
			).apply {
				details = WebAuthenticationDetailsSource().buildDetails(request)
			}
			SecurityContextHolder.getContext().authentication = authentication
			filterChain.doFilter(request, response)
		} catch (exception: InvalidAccessTokenException) {
			SecurityContextHolder.clearContext()
			apiSecurityErrorHandler.commence(
				request,
				response,
				BadCredentialsException("Invalid bearer token.", exception),
			)
		}
	}

	private fun extractBearerToken(authorization: String): String {
		if (!authorization.startsWith(BEARER_PREFIX) || authorization.length == BEARER_PREFIX.length) {
			throw InvalidAccessTokenException()
		}
		val token = authorization.substring(BEARER_PREFIX.length)
		if (token.isBlank() || token.any(Char::isWhitespace)) {
			throw InvalidAccessTokenException()
		}
		return token
	}

	companion object {
		private const val AUTHORIZATION_HEADER = "Authorization"
		private const val BEARER_PREFIX = "Bearer "
	}
}
