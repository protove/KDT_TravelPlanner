package com.ktcloud.travelplanner.global.logging

import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.core.Ordered
import org.springframework.core.annotation.Order
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import kotlin.math.max

internal enum class RequestLogLevel {
	INFO,
	WARN,
	ERROR,
}

internal object RequestLogLevelPolicy {
	fun resolve(httpStatus: Int): RequestLogLevel = when (httpStatus) {
		in 500..599 -> RequestLogLevel.ERROR
		in 400..499 -> RequestLogLevel.WARN
		else -> RequestLogLevel.INFO
	}
}

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
class RequestLoggingFilter(
	private val requestIdGenerator: RequestIdGenerator,
) : OncePerRequestFilter() {
	constructor() : this(RequestIdGenerator())

	private val requestLogger = LoggerFactory.getLogger(RequestLoggingFilter::class.java)

	override fun doFilterInternal(
		request: HttpServletRequest,
		response: HttpServletResponse,
		filterChain: FilterChain,
	) {
		val requestId = requestIdGenerator.resolve(request.getHeader(RequestIdGenerator.HEADER_NAME))
		val startedAt = System.nanoTime()
		var hasUnexpectedFailure = false

		MDC.put(RequestIdGenerator.MDC_KEY, requestId)
		response.setHeader(RequestIdGenerator.HEADER_NAME, requestId)

		try {
			filterChain.doFilter(request, response)
		} catch (throwable: Throwable) {
			hasUnexpectedFailure = true
			throw throwable
		} finally {
			val httpStatus = if (hasUnexpectedFailure && response.status < 500) {
				HttpServletResponse.SC_INTERNAL_SERVER_ERROR
			} else {
				response.status
			}
			val durationMilliseconds = max(0, (System.nanoTime() - startedAt) / NANOSECONDS_PER_MILLISECOND)

			try {
				logCompletedRequest(
					requestId = requestId,
					method = request.method,
					path = request.requestURI,
					httpStatus = httpStatus,
					durationMilliseconds = durationMilliseconds,
				)
			} finally {
				MDC.remove(RequestIdGenerator.MDC_KEY)
			}
		}
	}

	private fun logCompletedRequest(
		requestId: String,
		method: String,
		path: String,
		httpStatus: Int,
		durationMilliseconds: Long,
	) {
		MDC.put(RequestIdGenerator.MDC_KEY, requestId)
		MDC.put(METHOD_MDC_KEY, method)
		MDC.put(PATH_MDC_KEY, path)
		MDC.put(STATUS_MDC_KEY, httpStatus.toString())
		MDC.put(DURATION_MDC_KEY, durationMilliseconds.toString())

		try {
			when (RequestLogLevelPolicy.resolve(httpStatus)) {
				RequestLogLevel.INFO -> requestLogger.info(
					REQUEST_COMPLETED_MESSAGE,
					method,
					path,
					httpStatus,
					durationMilliseconds,
				)
				RequestLogLevel.WARN -> requestLogger.warn(
					REQUEST_COMPLETED_MESSAGE,
					method,
					path,
					httpStatus,
					durationMilliseconds,
				)
				RequestLogLevel.ERROR -> requestLogger.error(
					REQUEST_COMPLETED_MESSAGE,
					method,
					path,
					httpStatus,
					durationMilliseconds,
				)
			}
		} finally {
			MDC.remove(METHOD_MDC_KEY)
			MDC.remove(PATH_MDC_KEY)
			MDC.remove(STATUS_MDC_KEY)
			MDC.remove(DURATION_MDC_KEY)
		}
	}

	companion object {
		private const val REQUEST_COMPLETED_MESSAGE =
			"request completed method={} path={} status={} duration={}ms"
		private const val NANOSECONDS_PER_MILLISECOND = 1_000_000
		private const val METHOD_MDC_KEY = "method"
		private const val PATH_MDC_KEY = "path"
		private const val STATUS_MDC_KEY = "status"
		private const val DURATION_MDC_KEY = "duration"
	}
}
