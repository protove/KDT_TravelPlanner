package com.ktcloud.travelplanner.global.config

import com.ktcloud.travelplanner.testsupport.TestFixtures
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class UtcDateTimeProviderTest {
	@Test
	fun `auditing time comes from the configured UTC clock`() {
		val provider = UtcDateTimeProvider(TestFixtures.FIXED_CLOCK)

		assertEquals(TestFixtures.FIXED_INSTANT, provider.now.orElseThrow())
	}
}
