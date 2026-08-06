package com.ktcloud.travelplanner.global.logging

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Test
import java.util.UUID

class RequestIdGeneratorTest {

	private val requestIdGenerator = RequestIdGenerator()

	@Test
	fun `each request receives a new canonical UUID v4`() {
		val firstRequestId = requestIdGenerator.generate()
		val secondRequestId = requestIdGenerator.generate()
		val firstUuid = UUID.fromString(firstRequestId)
		val secondUuid = UUID.fromString(secondRequestId)

		assertEquals(firstUuid.toString(), firstRequestId)
		assertEquals(secondUuid.toString(), secondRequestId)
		assertEquals(4, firstUuid.version())
		assertEquals(4, secondUuid.version())
		assertNotEquals(firstRequestId, secondRequestId)
	}
}
