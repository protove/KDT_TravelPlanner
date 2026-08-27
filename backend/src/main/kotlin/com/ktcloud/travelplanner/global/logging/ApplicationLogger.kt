package com.ktcloud.travelplanner.global.logging

import com.ktcloud.travelplanner.global.exception.ErrorCode
import org.slf4j.LoggerFactory
import org.slf4j.spi.LoggingEventBuilder

internal enum class LogOutcome {
	SUCCESS,
	FAILURE,
	DENIED,
}

internal enum class RequestLogLevel {
	INFO,
	WARN,
	ERROR,
}

internal data class RequestCompletedLog(
	val requestId: String,
	val method: String,
	val route: String,
	val status: Int,
	val durationMs: Long,
	val outcome: LogOutcome,
	val errorCode: ErrorCode? = null,
)

internal data class UnexpectedFailureLog(
	val requestId: String,
	val summary: SafeExceptionSummary,
)

internal data class RequestLogDecision(
	val level: RequestLogLevel,
	val outcome: LogOutcome,
)

internal object RequestLogLevelPolicy {
	private val expectedInfoErrorCodes = setOf(
		ErrorCode.INVALID_REQUEST,
		ErrorCode.VALIDATION_ERROR,
		ErrorCode.MALFORMED_JSON,
		ErrorCode.INVALID_OAUTH_STATE,
		ErrorCode.RESOURCE_NOT_FOUND,
		ErrorCode.CONFLICT,
	)
	private val expectedWarningErrorCodes = setOf(
		ErrorCode.GOOGLE_PLACES_TIMEOUT,
		ErrorCode.GOOGLE_PLACES_QUOTA_EXCEEDED,
		ErrorCode.GOOGLE_ROUTES_TIMEOUT,
		ErrorCode.GOOGLE_ROUTES_QUOTA_EXCEEDED,
	)

	fun resolve(httpStatus: Int, errorCode: ErrorCode?): RequestLogDecision = when {
		httpStatus in 200..399 -> RequestLogDecision(RequestLogLevel.INFO, LogOutcome.SUCCESS)
		httpStatus == 401 || httpStatus == 403 -> RequestLogDecision(RequestLogLevel.WARN, LogOutcome.DENIED)
		httpStatus == 400 || httpStatus == 404 || httpStatus == 409 ->
			RequestLogDecision(RequestLogLevel.INFO, LogOutcome.FAILURE)
		errorCode in expectedInfoErrorCodes -> RequestLogDecision(RequestLogLevel.INFO, LogOutcome.FAILURE)
		errorCode in expectedWarningErrorCodes -> RequestLogDecision(RequestLogLevel.WARN, LogOutcome.FAILURE)
		httpStatus == 429 -> RequestLogDecision(RequestLogLevel.WARN, LogOutcome.FAILURE)
		httpStatus in 400..499 -> RequestLogDecision(RequestLogLevel.WARN, LogOutcome.FAILURE)
		httpStatus in 500..599 -> RequestLogDecision(RequestLogLevel.ERROR, LogOutcome.FAILURE)
		else -> RequestLogDecision(RequestLogLevel.INFO, LogOutcome.FAILURE)
	}
}

internal object ApplicationLogger {
	private val logger = LoggerFactory.getLogger(ApplicationLogger::class.java)

	fun info(message: String, vararg arguments: Any?) {
		logger.info(message, *arguments)
	}

	fun warn(message: String, vararg arguments: Any?) {
		logger.warn(message, *arguments)
	}

	fun error(message: String, vararg arguments: Any?) {
		logger.error(message, *arguments)
	}

	fun logRequestCompleted(requestLog: RequestCompletedLog, level: RequestLogLevel) {
		val loggingEvent = loggingEvent(level)
			.addKeyValue(EVENT_KEY, HTTP_REQUEST_COMPLETED_EVENT)
			.addKeyValue(METHOD_KEY, requestLog.method)
			.addKeyValue(ROUTE_KEY, requestLog.route)
			.addKeyValue(STATUS_KEY, requestLog.status)
			.addKeyValue(DURATION_MS_KEY, requestLog.durationMs)
			.addKeyValue(OUTCOME_KEY, requestLog.outcome.name)

		requestLog.errorCode?.let { loggingEvent.addKeyValue(ERROR_CODE_KEY, it.name) }
		loggingEvent.log(HTTP_REQUEST_COMPLETED_EVENT)
	}

	fun logUnexpectedFailure(failureLog: UnexpectedFailureLog) {
		logger.atError()
			.addKeyValue(EVENT_KEY, UNEXPECTED_REQUEST_FAILURE_EVENT)
			.addKeyValue(ERROR_TYPE_KEY, failureLog.summary.errorType)
			.addKeyValue(ERROR_FINGERPRINT_KEY, failureLog.summary.errorFingerprint)
			.addKeyValue(ERROR_FRAMES_KEY, failureLog.summary.errorFrames)
			.log(UNEXPECTED_REQUEST_FAILURE_EVENT)
	}

	private fun loggingEvent(level: RequestLogLevel): LoggingEventBuilder = when (level) {
		RequestLogLevel.INFO -> logger.atInfo()
		RequestLogLevel.WARN -> logger.atWarn()
		RequestLogLevel.ERROR -> logger.atError()
	}

	private const val HTTP_REQUEST_COMPLETED_EVENT = "HTTP_REQUEST_COMPLETED"
	private const val UNEXPECTED_REQUEST_FAILURE_EVENT = "UNEXPECTED_REQUEST_FAILURE"
	private const val EVENT_KEY = "event"
	private const val METHOD_KEY = "method"
	private const val ROUTE_KEY = "route"
	private const val STATUS_KEY = "status"
	private const val DURATION_MS_KEY = "durationMs"
	private const val OUTCOME_KEY = "outcome"
	private const val ERROR_CODE_KEY = "errorCode"
	private const val ERROR_TYPE_KEY = "errorType"
	private const val ERROR_FINGERPRINT_KEY = "errorFingerprint"
	private const val ERROR_FRAMES_KEY = "errorFrames"
}
