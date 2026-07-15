package com.ktcloud.travelplanner.global.response

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class ApiResponseTest {
	@Test
	fun `success wraps response data`() {
		val response = ApiResponse.success("travel")

		assertEquals("travel", response.data)
	}
}
