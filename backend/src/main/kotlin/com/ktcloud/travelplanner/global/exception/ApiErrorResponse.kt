package com.ktcloud.travelplanner.global.exception

import com.fasterxml.jackson.annotation.JsonInclude
import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.MDC

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

	fun resolveRequestId(response: HttpServletResponse): String {
		val requestId = MDC.get(RequestIdGenerator.MDC_KEY)
			?: requestIdGenerator.resolve(response.getHeader(RequestIdGenerator.HEADER_NAME))

		response.setHeader(RequestIdGenerator.HEADER_NAME, requestId)
		return requestId
	}
}
