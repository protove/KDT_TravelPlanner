package com.ktcloud.travelplanner.travel.model

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals

class CompanionTypeTest {
	@Test
	fun `defines the companion types supported by the product`() {
		assertEquals(
			listOf("SOLO", "COUPLE", "FAMILY", "FRIEND", "PET", "ETC"),
			CompanionType.entries.map(CompanionType::name),
		)
	}
}
