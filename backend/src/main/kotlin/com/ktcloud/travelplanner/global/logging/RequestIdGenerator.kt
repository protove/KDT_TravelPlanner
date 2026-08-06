package com.ktcloud.travelplanner.global.logging

import java.util.UUID

class RequestIdGenerator {
	fun generate(): String = UUID.randomUUID().toString()

	companion object {
		const val HEADER_NAME = "X-Request-Id"
		const val MDC_KEY = "requestId"
	}
}
