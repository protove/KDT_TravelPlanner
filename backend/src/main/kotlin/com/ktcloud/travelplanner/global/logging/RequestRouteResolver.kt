package com.ktcloud.travelplanner.global.logging

import jakarta.servlet.http.HttpServletRequest
import org.springframework.web.method.HandlerMethod
import org.springframework.web.servlet.HandlerMapping
import java.util.Locale

internal object RequestRouteResolver {
	private val supportedMethods = setOf(
		"GET",
		"HEAD",
		"POST",
		"PUT",
		"PATCH",
		"DELETE",
		"OPTIONS",
		"TRACE",
		"CONNECT",
	)

	fun resolveRoute(request: HttpServletRequest): String {
		val handler = request.getAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE)
		val route = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE) as? String

		return route
			?.takeIf { handler is HandlerMethod }
			?.takeIf(::isSafeRoute)
			?: UNRESOLVED_ROUTE
	}

	fun resolveMethod(method: String?): String {
		val normalizedMethod = method?.uppercase(Locale.ROOT)
		return normalizedMethod?.takeIf(supportedMethods::contains) ?: OTHER_METHOD
	}

	private fun isSafeRoute(route: String): Boolean =
		route.isNotBlank() && route.length <= MAX_ROUTE_LENGTH && route.none { it == '\r' || it == '\n' }

	const val UNRESOLVED_ROUTE = "UNRESOLVED"
	const val OTHER_METHOD = "OTHER"
	private const val MAX_ROUTE_LENGTH = 256
}
