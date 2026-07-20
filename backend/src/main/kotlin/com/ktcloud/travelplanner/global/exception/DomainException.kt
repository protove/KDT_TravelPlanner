package com.ktcloud.travelplanner.global.exception

open class DomainException(
	val errorCode: ErrorCode,
	message: String = errorCode.defaultMessage,
) : RuntimeException(message) {
	init {
		require(errorCode.httpStatus.is4xxClientError) {
			"DomainException must use a client error code."
		}
	}
}
