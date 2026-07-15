package com.ktcloud.travelplanner.global.exception

import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test
import org.springframework.http.HttpStatus

class ApiErrorResponseTest {
	@Test
	fun `error codes map to required HTTP statuses`() {
		assertEquals(HttpStatus.BAD_REQUEST, ErrorCode.INVALID_REQUEST.httpStatus)
		assertEquals(HttpStatus.BAD_REQUEST, ErrorCode.VALIDATION_ERROR.httpStatus)
		assertEquals(HttpStatus.BAD_REQUEST, ErrorCode.MALFORMED_JSON.httpStatus)
		assertEquals(HttpStatus.UNAUTHORIZED, ErrorCode.UNAUTHORIZED.httpStatus)
		assertEquals(HttpStatus.FORBIDDEN, ErrorCode.ACCESS_DENIED.httpStatus)
		assertEquals(HttpStatus.NOT_FOUND, ErrorCode.RESOURCE_NOT_FOUND.httpStatus)
		assertEquals(HttpStatus.CONFLICT, ErrorCode.CONFLICT.httpStatus)
		assertEquals(HttpStatus.INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_SERVER_ERROR.httpStatus)
	}

	@Test
	fun `validation field errors are sorted by field`() {
		val response = ApiErrorResponseFactory.create(
			errorCode = ErrorCode.VALIDATION_ERROR,
			requestId = "request-1",
			fieldErrors = listOf(
				FieldErrorResponse("title", "비어 있을 수 없습니다."),
				FieldErrorResponse("city", "비어 있을 수 없습니다."),
			),
		)

		assertEquals(listOf("city", "title"), response.fieldErrors?.map(FieldErrorResponse::field))
	}

	@Test
	fun `non validation response omits field errors`() {
		val response = ApiErrorResponseFactory.create(ErrorCode.CONFLICT, "request-2")
		val json = jacksonObjectMapper().writeValueAsString(response)

		assertFalse(json.contains("fieldErrors"))
	}

	@Test
	fun `domain exception rejects server error code`() {
		assertThrows(IllegalArgumentException::class.java) {
			DomainException(ErrorCode.INTERNAL_SERVER_ERROR)
		}
	}
}
