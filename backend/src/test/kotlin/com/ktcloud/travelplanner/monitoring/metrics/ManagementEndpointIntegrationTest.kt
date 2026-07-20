package com.ktcloud.travelplanner.monitoring.metrics

import com.ktcloud.travelplanner.TravelPlannerBackendApplication
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import io.micrometer.core.instrument.MeterRegistry
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.web.client.TestRestTemplate
import org.springframework.boot.test.web.server.LocalManagementPort
import org.springframework.boot.test.web.server.LocalServerPort
import org.springframework.context.annotation.Import
import org.springframework.http.HttpStatus
import org.springframework.test.context.ActiveProfiles

@ActiveProfiles("test")
@AutoConfigureObservability
@SpringBootTest(
	classes = [TravelPlannerBackendApplication::class],
	webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
	properties = ["management.server.port=0"],
)
@Import(TestcontainersConfiguration::class)
class ManagementEndpointIntegrationTest(
	@Autowired private val restTemplate: TestRestTemplate,
	@Autowired private val meterRegistry: MeterRegistry,
	@LocalServerPort private val applicationPort: Int,
	@LocalManagementPort private val managementPort: Int,
) {

	@Test
	fun `management server exposes health on a separate port`() {
		val response = restTemplate.getForEntity(
			"http://127.0.0.1:$managementPort/actuator/health",
			String::class.java,
		)

		assertNotEquals(applicationPort, managementPort)
		assertEquals(HttpStatus.OK, response.statusCode, response.body)
		assertTrue(response.body!!.contains("\"status\":\"UP\""))
	}

	@Test
	fun `management server exposes Prometheus JVM process and HTTP metrics`() {
		restTemplate.getForEntity("http://127.0.0.1:$applicationPort/api/ping", String::class.java)
		val actuatorLinks = restTemplate.getForEntity(
			"http://127.0.0.1:$managementPort/actuator",
			String::class.java,
		)

		val response = restTemplate.getForEntity(
			"http://127.0.0.1:$managementPort/actuator/prometheus",
			String::class.java,
		)

		assertTrue(meterRegistry.javaClass.name.contains("Prometheus"), meterRegistry.javaClass.name)
		assertTrue(actuatorLinks.body!!.contains("prometheus"), actuatorLinks.body)
		assertEquals(HttpStatus.OK, response.statusCode, response.body)
		assertTrue(response.body!!.contains("jvm_memory_used_bytes"))
		assertTrue(response.body!!.contains("process_cpu_usage"))
		assertTrue(response.body!!.contains("http_server_requests_seconds_count"))
		assertTrue(response.body!!.contains("http_server_requests_seconds_bucket"))
	}

	@Test
	fun `application server does not expose Prometheus endpoint`() {
		val response = restTemplate.getForEntity(
			"http://127.0.0.1:$applicationPort/actuator/prometheus",
			String::class.java,
		)

		assertEquals(HttpStatus.NOT_FOUND, response.statusCode)
	}
}
