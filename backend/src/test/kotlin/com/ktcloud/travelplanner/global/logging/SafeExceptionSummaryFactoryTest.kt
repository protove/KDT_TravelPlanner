package com.ktcloud.travelplanner.global.logging

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class SafeExceptionSummaryFactoryTest {

	@Test
	fun `summary contains only root type canonical application frames and fingerprint`() {
		val rootCause = IllegalArgumentException("token=secret-token url=https://private.example/path")
		rootCause.stackTrace = arrayOf(
			StackTraceElement(
				"com.ktcloud.travelplanner.travel.service.TravelService",
				"getTravel",
				"TravelService.kt",
				77,
			),
			StackTraceElement("java.net.URI", "create", "URI.java", 99),
		)
		val failure = IllegalStateException("select password from users", rootCause)

		val summary = SafeExceptionSummaryFactory(50).create(failure)
		val serializedSummary = summary.toString()

		assertEquals(IllegalArgumentException::class.java.name, summary.errorType)
		assertEquals(
			listOf("com.ktcloud.travelplanner.travel.service.TravelService#getTravel"),
			summary.errorFrames,
		)
		assertTrue(summary.errorFingerprint.matches(Regex("^[0-9a-f]{64}$")))
		assertFalse(serializedSummary.contains("secret-token"))
		assertFalse(serializedSummary.contains("private.example"))
		assertFalse(serializedSummary.contains("select password"))
		assertFalse(serializedSummary.contains("TravelService.kt"))
		assertFalse(serializedSummary.contains(":77"))
	}

	@Test
	fun `display limit does not change fingerprint input`() {
		val failure = IllegalStateException("not logged")
		failure.stackTrace = Array(60) { index ->
			StackTraceElement(
				"com.ktcloud.travelplanner.timeline.service.TimelineService$index",
				"loadTimeline",
				"TimelineService.kt",
				index + 1,
			)
		}

		val developmentSummary = SafeExceptionSummaryFactory(50).create(failure)
		val productionSummary = SafeExceptionSummaryFactory(5).create(failure)

		assertEquals(50, developmentSummary.errorFrames.size)
		assertEquals(5, productionSummary.errorFrames.size)
		assertEquals(developmentSummary.errorFingerprint, productionSummary.errorFingerprint)
	}

	@Test
	fun `fingerprint excludes messages suppressed failures file names and line numbers`() {
		val firstFailure = IllegalStateException("token=first-secret url=https://first.example")
		firstFailure.stackTrace = arrayOf(
			StackTraceElement(
				"com.ktcloud.travelplanner.travel.service.TravelService",
				"loadTravel",
				"FirstSecret.kt",
				11,
			),
		)
		firstFailure.addSuppressed(IllegalArgumentException("select password from users"))
		val secondFailure = IllegalStateException("token=second-secret url=https://second.example")
		secondFailure.stackTrace = arrayOf(
			StackTraceElement(
				"com.ktcloud.travelplanner.travel.service.TravelService",
				"loadTravel",
				"SecondSecret.kt",
				999,
			),
		)
		secondFailure.addSuppressed(UnsupportedOperationException("oauth-client-secret"))

		val firstSummary = SafeExceptionSummaryFactory(5).create(firstFailure)
		val secondSummary = SafeExceptionSummaryFactory(5).create(secondFailure)

		assertEquals(firstSummary.errorFingerprint, secondSummary.errorFingerprint)

		secondFailure.stackTrace = arrayOf(
			StackTraceElement(
				"com.ktcloud.travelplanner.travel.service.TravelService",
				"loadAnotherTravel",
				"SecondSecret.kt",
				999,
			),
		)
		val differentMethodSummary = SafeExceptionSummaryFactory(5).create(secondFailure)
		val differentType = IllegalArgumentException("same frame, different type")
		differentType.stackTrace = firstFailure.stackTrace
		val differentTypeSummary = SafeExceptionSummaryFactory(5).create(differentType)

		assertFalse(firstSummary.errorFingerprint == differentMethodSummary.errorFingerprint)
		assertFalse(firstSummary.errorFingerprint == differentTypeSummary.errorFingerprint)
	}

	@Test
	fun `cause traversal stops after twenty throwable nodes`() {
		var failureBeyondLimit: Throwable = IllegalArgumentException("node beyond the limit")
		repeat(20) { index ->
			failureBeyondLimit = IllegalStateException("wrapper-$index", failureBeyondLimit)
		}
		var failureAtLimit: Throwable = IllegalArgumentException("twentieth node")
		repeat(19) { index ->
			failureAtLimit = IllegalStateException("wrapper-$index", failureAtLimit)
		}

		assertEquals(
			IllegalStateException::class.java.name,
			SafeExceptionSummaryFactory(5).create(failureBeyondLimit).errorType,
		)
		assertEquals(
			IllegalArgumentException::class.java.name,
			SafeExceptionSummaryFactory(5).create(failureAtLimit).errorType,
		)
	}

	@Test
	fun `cause traversal is cycle safe and bounded`() {
		val firstFailure = IllegalStateException("first-secret")
		val secondFailure = IllegalArgumentException("second-secret")
		firstFailure.initCause(secondFailure)
		secondFailure.initCause(firstFailure)

		val summary = SafeExceptionSummaryFactory(5).create(firstFailure)

		assertEquals(IllegalArgumentException::class.java.name, summary.errorType)
		assertTrue(summary.errorFingerprint.matches(Regex("^[0-9a-f]{64}$")))
		assertFalse(summary.toString().contains("secret"))
	}
}
