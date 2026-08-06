package com.ktcloud.travelplanner.global.logging

import com.ktcloud.travelplanner.global.exception.ErrorCode
import jakarta.servlet.http.HttpServletRequest

internal object RequestLoggingContext {
	fun setRequestId(request: HttpServletRequest, requestId: String) {
		request.setAttribute(REQUEST_ID_ATTRIBUTE, requestId)
	}

	fun getRequestId(request: HttpServletRequest): String? =
		request.getAttribute(REQUEST_ID_ATTRIBUTE) as? String

	fun setErrorCode(request: HttpServletRequest, errorCode: ErrorCode) {
		request.setAttribute(ERROR_CODE_ATTRIBUTE, errorCode)
	}

	fun getErrorCode(request: HttpServletRequest): ErrorCode? =
		request.getAttribute(ERROR_CODE_ATTRIBUTE) as? ErrorCode

	private const val REQUEST_ID_ATTRIBUTE =
		"com.ktcloud.travelplanner.global.logging.requestId"
	private const val ERROR_CODE_ATTRIBUTE =
		"com.ktcloud.travelplanner.global.logging.errorCode"
}
