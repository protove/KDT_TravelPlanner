package com.ktcloud.travelplanner.global.exception

import com.fasterxml.jackson.annotation.JsonInclude
import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import com.ktcloud.travelplanner.global.logging.RequestLoggingContext
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse

data class FieldErrorResponse(
	val field: String,
	val reason: String,
)

data class ApiErrorResponse(
	val code: String,
	val message: String,
	val requestId: String,
	@JsonInclude(JsonInclude.Include.NON_NULL)
	val fieldErrors: List<FieldErrorResponse>? = null,
)

internal object ApiErrorResponseFactory {
	private val requestIdGenerator = RequestIdGenerator()

	fun create(
		errorCode: ErrorCode,
		requestId: String,
		message: String = errorCode.defaultMessage,
		fieldErrors: List<FieldErrorResponse>? = null,
	): ApiErrorResponse = ApiErrorResponse(
		code = errorCode.name,
		message = message,
		requestId = requestId,
		fieldErrors = fieldErrors?.sortedBy(FieldErrorResponse::field),
	)

	fun resolveRequestId(request: HttpServletRequest, response: HttpServletResponse): String {
		val requestId = RequestLoggingContext.getRequestId(request)
			?: requestIdGenerator.generate().also { RequestLoggingContext.setRequestId(request, it) }

		response.setHeader(RequestIdGenerator.HEADER_NAME, requestId)
		return requestId
	}
}
