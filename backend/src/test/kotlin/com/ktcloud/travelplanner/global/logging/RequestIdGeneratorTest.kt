package com.ktcloud.travelplanner.global.logging

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.UUID

class RequestIdGeneratorTest {

	private val requestIdGenerator = RequestIdGenerator()

	@Test
	fun `valid request id is preserved`() {
		val requestId = "client.Request_Id-123"

		assertEquals(requestId, requestIdGenerator.resolve(requestId))
	}

	@Test
	fun `one and sixty four valid characters are accepted`() {
		val oneCharacterRequestId = "a"
		val sixtyFourCharacterRequestId = "a".repeat(64)

		assertEquals(oneCharacterRequestId, requestIdGenerator.resolve(oneCharacterRequestId))
		assertEquals(sixtyFourCharacterRequestId, requestIdGenerator.resolve(sixtyFourCharacterRequestId))
	}

	@Test
	fun `missing or invalid request id is replaced with UUID`() {
		val invalidRequestIds = listOf(
			null,
			"",
			"contains space",
			"한글",
			"a".repeat(65),
		)

		invalidRequestIds.forEach { invalidRequestId ->
			val generatedRequestId = requestIdGenerator.resolve(invalidRequestId)

			assertNotEquals(invalidRequestId, generatedRequestId)
			assertTrue(runCatching { UUID.fromString(generatedRequestId) }.isSuccess)
		}
	}
}
