package com.ktcloud.travelplanner.global.exception

open class ExternalServiceException(
	val errorCode: ErrorCode,
	message: String = errorCode.defaultMessage,
	cause: Throwable? = null,
) : RuntimeException(message, cause) {
	init {
		require(errorCode.httpStatus.is5xxServerError) {
			"ExternalServiceException must use a server error code."
		}
	}
}
