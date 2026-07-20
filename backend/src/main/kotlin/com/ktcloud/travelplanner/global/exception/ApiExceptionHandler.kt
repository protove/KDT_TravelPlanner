package com.ktcloud.travelplanner.global.exception

import jakarta.servlet.http.HttpServletResponse
import jakarta.validation.ConstraintViolationException
import org.slf4j.LoggerFactory
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
class ApiExceptionHandler {
	private val logger = LoggerFactory.getLogger(ApiExceptionHandler::class.java)

	@ExceptionHandler(DomainException::class)
	fun handleDomainException(
		exception: DomainException,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = exception.errorCode,
		response = response,
		message = exception.message ?: exception.errorCode.defaultMessage,
	)

	@ExceptionHandler(ExternalServiceException::class)
	fun handleExternalServiceException(
		exception: ExternalServiceException,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = exception.errorCode,
		response = response,
	)

	@ExceptionHandler(MethodArgumentNotValidException::class)
	fun handleMethodArgumentNotValidException(
		exception: MethodArgumentNotValidException,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildValidationResponse(
		fieldErrors = exception.bindingResult.fieldErrors.map(::toFieldErrorResponse),
		response = response,
	)

	@ExceptionHandler(BindException::class)
	fun handleBindException(
		exception: BindException,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildValidationResponse(
		fieldErrors = exception.bindingResult.fieldErrors.map(::toFieldErrorResponse),
		response = response,
	)

	@ExceptionHandler(HttpMessageNotReadableException::class)
	fun handleHttpMessageNotReadableException(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.MALFORMED_JSON, response)

	@ExceptionHandler(
		MethodArgumentTypeMismatchException::class,
		MissingServletRequestParameterException::class,
		ConstraintViolationException::class,
	)
	fun handleInvalidRequest(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.INVALID_REQUEST, response)

	@ExceptionHandler(NoHandlerFoundException::class, NoResourceFoundException::class)
	fun handleResourceNotFound(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.RESOURCE_NOT_FOUND, response)

	@ExceptionHandler(AuthenticationException::class)
	fun handleAuthenticationException(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.UNAUTHORIZED, response)

	@ExceptionHandler(AccessDeniedException::class)
	fun handleAccessDeniedException(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.ACCESS_DENIED, response)

	@ExceptionHandler(HttpRequestMethodNotSupportedException::class)
	fun handleMethodNotSupported(
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(ErrorCode.INVALID_REQUEST, response)

	@ExceptionHandler(Exception::class)
	fun handleUnexpectedException(
		exception: Exception,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> {
		val requestId = ApiErrorResponseFactory.resolveRequestId(response)
		logger.error("unexpected request failure requestId={}", requestId, exception)
		return buildResponse(ErrorCode.INTERNAL_SERVER_ERROR, response, requestId = requestId)
	}

	private fun buildValidationResponse(
		fieldErrors: List<FieldErrorResponse>,
		response: HttpServletResponse,
	): ResponseEntity<ApiErrorResponse> = buildResponse(
		errorCode = ErrorCode.VALIDATION_ERROR,
		response = response,
		fieldErrors = fieldErrors,
	)

	private fun buildResponse(
		errorCode: ErrorCode,
		response: HttpServletResponse,
		message: String = errorCode.defaultMessage,
		fieldErrors: List<FieldErrorResponse>? = null,
		requestId: String = ApiErrorResponseFactory.resolveRequestId(response),
	): ResponseEntity<ApiErrorResponse> = ResponseEntity
		.status(errorCode.httpStatus)
		.body(ApiErrorResponseFactory.create(errorCode, requestId, message, fieldErrors))

	private fun toFieldErrorResponse(fieldError: org.springframework.validation.FieldError): FieldErrorResponse =
		FieldErrorResponse(
			field = fieldError.field,
			reason = fieldError.defaultMessage ?: DEFAULT_FIELD_ERROR_REASON,
		)

	companion object {
		private const val DEFAULT_FIELD_ERROR_REASON = "올바르지 않은 값입니다."
	}
}
