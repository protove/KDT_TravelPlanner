package com.ktcloud.travelplanner.testsupport

import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID

object TestFixtures {
	val FIXED_INSTANT: Instant = Instant.parse("2026-01-01T00:00:00Z")
	val FIXED_CLOCK: Clock = Clock.fixed(FIXED_INSTANT, ZoneOffset.UTC)
	val USER_ID: UUID = UUID.fromString("00000000-0000-0000-0000-000000000001")
}
