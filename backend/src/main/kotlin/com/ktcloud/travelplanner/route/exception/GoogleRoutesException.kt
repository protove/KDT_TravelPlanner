package com.ktcloud.travelplanner.route.exception

import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.exception.ExternalServiceException

sealed class GoogleRoutesException(errorCode: ErrorCode, cause: Throwable? = null) :
	ExternalServiceException(errorCode, cause = cause)

class GoogleRoutesNotConfiguredException : GoogleRoutesException(ErrorCode.GOOGLE_ROUTES_NOT_CONFIGURED)

class GoogleRoutesTimeoutException(cause: Throwable) : GoogleRoutesException(ErrorCode.GOOGLE_ROUTES_TIMEOUT, cause)

class GoogleRoutesQuotaExceededException(cause: Throwable) :
	GoogleRoutesException(ErrorCode.GOOGLE_ROUTES_QUOTA_EXCEEDED, cause)

class GoogleRoutesProviderException(cause: Throwable? = null) :
	GoogleRoutesException(ErrorCode.GOOGLE_ROUTES_ERROR, cause)
