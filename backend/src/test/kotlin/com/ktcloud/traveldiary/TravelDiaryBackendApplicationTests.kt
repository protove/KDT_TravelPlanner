package com.ktcloud.traveldiary

import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get

@WebMvcTest(PingController::class)
class TravelDiaryBackendApplicationTests(
	@Autowired private val mockMvc: MockMvc,
) {

	@Test
	fun `ping returns application status`() {
		mockMvc.get("/api/ping")
			.andExpect {
				status { isOk() }
				jsonPath("$.status", equalTo("ok"))
				jsonPath("$.application", equalTo("travel-diary-backend"))
			}
	}
}
