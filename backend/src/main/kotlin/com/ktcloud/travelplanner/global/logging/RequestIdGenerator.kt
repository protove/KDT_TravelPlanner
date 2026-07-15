package com.ktcloud.travelplanner.global.logging

import java.util.UUID

class RequestIdGenerator {

	fun resolve(requestIdHeader: String?): String =
		requestIdHeader
			?.takeIf(REQUEST_ID_PATTERN::matches)
			?: UUID.randomUUID().toString()

	companion object {
		const val HEADER_NAME = "X-Request-Id"
		const val MDC_KEY = "requestId"

		private val REQUEST_ID_PATTERN = Regex("^[A-Za-z0-9._-]{1,64}$")
	}
}
