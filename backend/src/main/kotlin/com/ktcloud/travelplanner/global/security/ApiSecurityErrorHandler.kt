package com.ktcloud.travelplanner.global.security

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.global.exception.ApiErrorResponseFactory
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.logging.RequestLoggingContext
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.springframework.http.MediaType
import org.springframework.security.access.AccessDeniedException
import org.springframework.security.core.AuthenticationException
import org.springframework.security.web.AuthenticationEntryPoint
import org.springframework.security.web.access.AccessDeniedHandler
import org.springframework.stereotype.Component
import java.nio.charset.StandardCharsets

@Component
class ApiSecurityErrorHandler(
	private val objectMapper: ObjectMapper,
) : AuthenticationEntryPoint, AccessDeniedHandler {

	override fun commence(
		request: HttpServletRequest,
		response: HttpServletResponse,
		authenticationException: AuthenticationException,
	) {
		write(request, response, ErrorCode.UNAUTHORIZED)
	}

	override fun handle(
		request: HttpServletRequest,
		response: HttpServletResponse,
		accessDeniedException: AccessDeniedException,
	) {
		write(request, response, ErrorCode.ACCESS_DENIED)
	}

	private fun write(request: HttpServletRequest, response: HttpServletResponse, errorCode: ErrorCode) {
		if (response.isCommitted) {
			return
		}

		RequestLoggingContext.setErrorCode(request, errorCode)
		val requestId = ApiErrorResponseFactory.resolveRequestId(request, response)
		response.status = errorCode.httpStatus.value()
		response.contentType = MediaType.APPLICATION_JSON_VALUE
		response.characterEncoding = StandardCharsets.UTF_8.name()
		objectMapper.writeValue(
			response.outputStream,
			ApiErrorResponseFactory.create(errorCode, requestId),
		)
	}
}
