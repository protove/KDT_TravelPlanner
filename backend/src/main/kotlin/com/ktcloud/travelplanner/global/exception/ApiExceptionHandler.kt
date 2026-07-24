package com.ktcloud.travelplanner.global.exception

import com.ktcloud.travelplanner.global.logging.ApplicationLogger
import com.ktcloud.travelplanner.global.logging.RequestLoggingContext
import com.ktcloud.travelplanner.global.logging.SafeExceptionSummaryFactory
import com.ktcloud.travelplanner.global.logging.UnexpectedFailureLog
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.ConstraintViolationException
import org.springframework.beans.factory.annotation.Value
import org.springframework.http.ResponseEntity
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.security.access.AccessDeniedException
import org.springframework.security.core.AuthenticationException
import org.springframework.validation.BindException
import org.springframework.web.HttpRequestMethodNotSupportedException
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.web.bind.MissingServletRequestParameterException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException
import org.springframework.web.servlet.NoHandlerFoundException
import org.springframework.web.servlet.resource.NoResourceFoundException

@RestControllerAdvice
class ApiExceptionHandler(
	@Value("\${app.logging.error-frame-limit:5}") displayedFrameLimit: Int,
) {
	private val safeExceptionSummaryFactory = SafeExceptionSummaryFactory(displayedFrameLimit)

	@ExceptionHandler(DomainException::class)
	fun handleDomainException(
		exception: DomainException,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = exception.errorCode,
		request = request,
		response = response,
		message = exception.message ?: exception.errorCode.defaultMessage,
	)

	@ExceptionHandler(ExternalServiceException::class)
	fun handleExternalServiceException(
		exception: ExternalServiceException,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = exception.errorCode,
		request = request,
		response = response,
	)

	@ExceptionHandler(MethodArgumentNotValidException::class)
	fun handleMethodArgumentNotValidException(
		exception: MethodArgumentNotValidException,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildValidationResponse(
		fieldErrors = exception.bindingResult.fieldErrors.map(::toFieldErrorResponse),
		request = request,
		response = response,
	)

	@ExceptionHandler(BindException::class)
	fun handleBindException(
		exception: BindException,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildValidationResponse(
		fieldErrors = exception.bindingResult.fieldErrors.map(::toFieldErrorResponse),
		request = request,
		response = response,
	)

	@ExceptionHandler(HttpMessageNotReadableException::class)
	fun handleHttpMessageNotReadableException(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.MALFORMED_JSON, request, response)

	@ExceptionHandler(
		MethodArgumentTypeMismatchException::class,
		MissingServletRequestParameterException::class,
		ConstraintViolationException::class,
	)
	fun handleInvalidRequest(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.INVALID_REQUEST, request, response)

	@ExceptionHandler(NoHandlerFoundException::class, NoResourceFoundException::class)
	fun handleResourceNotFound(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.RESOURCE_NOT_FOUND, request, response)

	@ExceptionHandler(AuthenticationException::class)
	fun handleAuthenticationException(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.UNAUTHORIZED, request, response)

	@ExceptionHandler(AccessDeniedException::class)
	fun handleAccessDeniedException(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.ACCESS_DENIED, request, response)

	@ExceptionHandler(HttpRequestMethodNotSupportedException::class)
	fun handleMethodNotSupported(
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.INVALID_REQUEST, request, response)

	@ExceptionHandler(Exception::class)
	fun handleUnexpectedException(
		exception: Exception,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> {
		RequestLoggingContext.setErrorCode(request, ErrorCode.INTERNAL_SERVER_ERROR)
		val requestId = ApiErrorResponseFactory.resolveRequestId(request, response)
		ApplicationLogger.logUnexpectedFailure(
			UnexpectedFailureLog(
				requestId = requestId,
				summary = safeExceptionSummaryFactory.create(exception),
			),
		)
		return buildResponse(ErrorCode.INTERNAL_SERVER_ERROR, request, response, requestId = requestId)
	}

	private fun buildValidationResponse(
		fieldErrors: List<FieldErrorResponse>,
		request: HttpServletRequest,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = ErrorCode.VALIDATION_ERROR,
		request = request,
		response = response,
		fieldErrors = fieldErrors,
	)

	private fun buildResponse(
		errorCode: ErrorCode,
		request: HttpServletRequest,
		response: HttpServletResponse,
		message: String = errorCode.defaultMessage,
		fieldErrors: List<FieldErrorResponse>? = null,
		requestId: String? = null,
	): ResponseEntity<ApiErrorResponse> {
		RequestLoggingContext.setErrorCode(request, errorCode)
		val resolvedRequestId = requestId ?: ApiErrorResponseFactory.resolveRequestId(request, response)

		return ResponseEntity
			.status(errorCode.httpStatus)
			.body(ApiErrorResponseFactory.create(errorCode, resolvedRequestId, message, fieldErrors))
	}

	private fun toFieldErrorResponse(fieldError: org.springframework.validation.FieldError): FieldErrorResponse =
		FieldErrorResponse(
			field = fieldError.field,
			reason = fieldError.defaultMessage ?: DEFAULT_FIELD_ERROR_REASON,
		)

	companion object {
		private const val DEFAULT_FIELD_ERROR_REASON = "올바르지 않은 값입니다."
	}
}
