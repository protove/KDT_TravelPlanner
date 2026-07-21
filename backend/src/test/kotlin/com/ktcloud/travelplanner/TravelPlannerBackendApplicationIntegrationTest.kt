package com.ktcloud.travelplanner

import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.ktcloud.travelplanner.route.config.GoogleRoutesProperties
import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import kotlin.test.assertEquals

class TravelPlannerBackendApplicationIntegrationTest(
	@Autowired private val googlePlacesProperties: GooglePlacesProperties,
	@Autowired private val googleRoutesProperties: GoogleRoutesProperties,
) : ContainerIntegrationTestSupport() {

	@Test
	fun `Spring context binds one Google Maps key to Places and Routes`() {
		assertEquals(GOOGLE_MAPS_API_KEY, googlePlacesProperties.apiKey)
		assertEquals(GOOGLE_MAPS_API_KEY, googleRoutesProperties.apiKey)
	}

	companion object {
		private const val GOOGLE_MAPS_API_KEY = "integration-google-maps-key"

		@JvmStatic
		@DynamicPropertySource
		fun googleMapsProperties(registry: DynamicPropertyRegistry) {
			registry.add("GOOGLE_MAPS_API_KEY") { GOOGLE_MAPS_API_KEY }
		}
	}
}
