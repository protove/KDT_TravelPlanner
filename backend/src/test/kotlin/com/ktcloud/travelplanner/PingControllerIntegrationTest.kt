package com.ktcloud.travelplanner

import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.options

@WebMvcTest(PingController::class)
@Import(WebConfig::class)
class PingControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
) {

	@Test
	fun `ping keeps its endpoint and returns TravelPlanner application name`() {
		mockMvc.get("/api/ping")
			.andExpect {
				status { isOk() }
				jsonPath("$.status", equalTo("ok"))
				jsonPath("$.application", equalTo("travel-planner-backend"))
			}
	}

	@Test
	fun `allowed frontend origin keeps CORS access`() {
		mockMvc.options("/api/ping") {
			header(HttpHeaders.ORIGIN, "http://localhost:3000")
			header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "GET")
		}
			.andExpect {
				status { isOk() }
				header { string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "http://localhost:3000") }
				header { string(HttpHeaders.ACCESS_CONTROL_ALLOW_CREDENTIALS, "true") }
			}
	}
}
