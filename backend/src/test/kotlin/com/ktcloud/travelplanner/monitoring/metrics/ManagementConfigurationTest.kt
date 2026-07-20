package com.ktcloud.travelplanner.monitoring.metrics

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.config.YamlPropertiesFactoryBean
import org.springframework.core.io.ClassPathResource

class ManagementConfigurationTest {

	@Test
	fun `management configuration separates port and exposes Prometheus metrics`() {
		val properties = YamlPropertiesFactoryBean().apply {
			setResources(ClassPathResource("application.yml"))
		}.getObject()!!

		assertEquals(
			"\${MANAGEMENT_SERVER_PORT:9091}",
			properties.getProperty("management.server.port"),
		)
		assertEquals(
			"health,info,prometheus",
			properties.getProperty("management.endpoints.web.exposure.include"),
		)
		assertEquals(
			"true",
			properties.getProperty("management.metrics.distribution.percentiles-histogram.http.server.requests"),
		)
	}
}
