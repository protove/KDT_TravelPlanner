package com.ktcloud.travelplanner.global.exception

import org.springframework.http.HttpStatus

enum class ErrorCode(
	val httpStatus: HttpStatus,
	val defaultMessage: String,
) {
	INVALID_REQUEST(HttpStatus.BAD_REQUEST, "요청이 올바르지 않습니다."),
	VALIDATION_ERROR(HttpStatus.BAD_REQUEST, "요청값이 올바르지 않습니다."),
	MALFORMED_JSON(HttpStatus.BAD_REQUEST, "요청 본문을 읽을 수 없습니다."),
	UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "인증이 필요합니다."),
	INVALID_AUTHORIZATION_CODE(HttpStatus.UNAUTHORIZED, "인증 코드가 유효하지 않습니다."),
	ACCESS_DENIED(HttpStatus.FORBIDDEN, "접근 권한이 없습니다."),
	INVALID_OAUTH_STATE(HttpStatus.BAD_REQUEST, "OAuth state가 유효하지 않습니다."),
	RESOURCE_NOT_FOUND(HttpStatus.NOT_FOUND, "요청한 리소스를 찾을 수 없습니다."),
	CONFLICT(HttpStatus.CONFLICT, "요청이 현재 상태와 충돌합니다."),
	OAUTH_PROVIDER_ERROR(HttpStatus.BAD_GATEWAY, "OAuth 제공자 통신에 실패했습니다."),
	INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "서버 내부 오류가 발생했습니다."),
}
