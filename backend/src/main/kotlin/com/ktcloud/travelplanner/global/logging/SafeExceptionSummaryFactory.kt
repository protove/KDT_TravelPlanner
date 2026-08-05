package com.ktcloud.travelplanner.global.logging

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Collections
import java.util.IdentityHashMap

internal data class SafeExceptionSummary(
	val errorType: String,
	val errorFingerprint: String,
	val errorFrames: List<String>,
)

internal class SafeExceptionSummaryFactory(
	displayedFrameLimit: Int,
) {
	private val displayedFrameLimit = displayedFrameLimit.coerceIn(0, MAX_CANONICAL_FRAMES)

	fun create(throwable: Throwable): SafeExceptionSummary {
		val causeChain = resolveCauseChain(throwable)
		val rootCause = causeChain.last()
		val canonicalFrames = causeChain
			.asReversed()
			.asSequence()
			.map(::resolveApplicationFrames)
			.firstOrNull(List<String>::isNotEmpty)
			.orEmpty()
		val errorType = rootCause.javaClass.name

		return SafeExceptionSummary(
			errorType = errorType,
			errorFingerprint = createFingerprint(errorType, canonicalFrames),
			errorFrames = canonicalFrames.take(displayedFrameLimit),
		)
	}

	private fun resolveCauseChain(throwable: Throwable): List<Throwable> {
		val visited = Collections.newSetFromMap(IdentityHashMap<Throwable, Boolean>())
		val causes = mutableListOf<Throwable>()
		var current: Throwable? = throwable

		while (current != null && causes.size < MAX_CAUSE_DEPTH && visited.add(current)) {
			causes += current
			current = current.cause
		}

		return causes
	}

	private fun resolveApplicationFrames(throwable: Throwable): List<String> = throwable.stackTrace
		.asSequence()
		.filter { it.className.startsWith(APPLICATION_PACKAGE_PREFIX) }
		.map { "${it.className}#${it.methodName}" }
		.take(MAX_CANONICAL_FRAMES)
		.toList()

	private fun createFingerprint(errorType: String, canonicalFrames: List<String>): String {
		val canonicalFailure = buildString {
			append(FINGERPRINT_VERSION)
			append(FINGERPRINT_SEPARATOR)
			append(errorType)
			canonicalFrames.forEach { frame ->
				append(FINGERPRINT_SEPARATOR)
				append(frame)
			}
		}
		val digest = MessageDigest.getInstance(FINGERPRINT_ALGORITHM)
			.digest(canonicalFailure.toByteArray(StandardCharsets.UTF_8))

		return buildString(digest.size * 2) {
			digest.forEach { byte ->
				val value = byte.toInt() and 0xff
				append(HEX_DIGITS[value ushr 4])
				append(HEX_DIGITS[value and 0x0f])
			}
		}
	}

	companion object {
		private const val APPLICATION_PACKAGE_PREFIX = "com.ktcloud.travelplanner."
		private const val MAX_CAUSE_DEPTH = 20
		private const val MAX_CANONICAL_FRAMES = 50
		private const val FINGERPRINT_VERSION = "v1"
		private const val FINGERPRINT_SEPARATOR = '\u0000'
		private const val FINGERPRINT_ALGORITHM = "SHA-256"
		private const val HEX_DIGITS = "0123456789abcdef"
	}
}
