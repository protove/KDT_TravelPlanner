package com.ktcloud.travelplanner.testsupport

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import java.time.ZoneOffset
import java.util.UUID

class TestFixturesTest {

	@Test
	fun `fixed clock and identifiers are deterministic`() {
		assertEquals(TestFixtures.FIXED_INSTANT, TestFixtures.FIXED_CLOCK.instant())
		assertEquals(ZoneOffset.UTC, TestFixtures.FIXED_CLOCK.zone)
		assertEquals(
			UUID.fromString("00000000-0000-0000-0000-000000000001"),
			TestFixtures.USER_ID,
		)
	}
}
