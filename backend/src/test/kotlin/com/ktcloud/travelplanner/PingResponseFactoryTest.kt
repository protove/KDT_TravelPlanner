package com.ktcloud.travelplanner

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class PingResponseFactoryTest {

	@Test
	fun `configured application name and first profile are mapped`() {
		val response = PingResponseFactory.create(
			applicationName = "travel-planner-backend",
			activeProfiles = arrayOf("dev", "local"),
		)

		assertEquals("ok", response.status)
		assertEquals("travel-planner-backend", response.application)
		assertEquals("dev", response.profile)
	}

	@Test
	fun `missing values use TravelPlanner defaults`() {
		val response = PingResponseFactory.create(
			applicationName = null,
			activeProfiles = emptyArray(),
		)

		assertEquals("travel-planner-backend", response.application)
		assertEquals("default", response.profile)
	}
}
