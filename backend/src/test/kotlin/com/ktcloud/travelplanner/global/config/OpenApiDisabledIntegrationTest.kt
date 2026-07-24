package com.ktcloud.travelplanner.global.config

import com.ktcloud.travelplanner.TravelPlannerBackendApplication
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get

@ActiveProfiles("test")
@SpringBootTest(
	classes = [TravelPlannerBackendApplication::class],
	properties = [
		"springdoc.api-docs.enabled=false",
		"springdoc.swagger-ui.enabled=false",
	],
	webEnvironment = SpringBootTest.WebEnvironment.MOCK,
)
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
class OpenApiDisabledIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
) {
	@Test
	fun `disabled documentation endpoints return not found`() {
		mockMvc.get("/v3/api-docs")
			.andExpect {
				status { isNotFound() }
			}

		mockMvc.get("/v3/api-docs.yaml")
			.andExpect {
				status { isNotFound() }
			}

		mockMvc.get("/swagger-ui.html")
			.andExpect {
				status { isNotFound() }
			}
	}
}
