package com.ktcloud.travelplanner.global.logging

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.extension
import kotlin.io.path.name
import kotlin.io.path.readText

class LoggingPolicyTest {

	@Test
	fun `production code uses only the approved logging boundary`() {
		val kotlinSources = productionKotlinSources()
		val directLoggerTokens = listOf(
			"LoggerFactory",
			"org.slf4j.Logger",
			"org.slf4j.spi.LoggingEventBuilder",
			"ch.qos.logback.",
			"java.util.logging.",
			"org.apache.logging.log4j.",
			"KotlinLogging",
			"System.getLogger",
		)
		val directLoggerUsers = kotlinSources.filter { source ->
			val text = source.readText()
			directLoggerTokens.any(text::contains)
		}
		val mdcUsers = kotlinSources.filter { source ->
			val text = source.readText()
			text.contains("org.slf4j.MDC") || text.contains("MDC.")
		}

		assertEquals(listOf("ApplicationLogger.kt"), directLoggerUsers.map { it.name }.sorted())
		assertEquals(listOf("RequestLoggingFilter.kt"), mdcUsers.map { it.name }.sorted())
	}

	@Test
	fun `production code does not write directly to process output or print stack traces`() {
		val forbiddenPatterns = listOf(
			Regex("System\\.(out|err)"),
			Regex("\\bprint(StackTrace)?\\s*\\("),
			Regex("\\bprintln\\s*\\("),
		)
		val violations = productionKotlinSources().flatMap { source ->
			val text = source.readText()
			forbiddenPatterns
				.filter { it.containsMatchIn(text) }
				.map { source.name to it.pattern }
		}

		assertTrue(violations.isEmpty(), "Forbidden logging calls: $violations")
	}

	private fun productionKotlinSources(): List<Path> {
		val sourceRoot = Path.of(System.getProperty("user.dir"), "src", "main", "kotlin")
		require(Files.isDirectory(sourceRoot)) { "Production Kotlin source root not found: $sourceRoot" }

		return Files.walk(sourceRoot).use { paths ->
			paths.filter { Files.isRegularFile(it) && it.extension == "kt" }.toList()
		}
	}
}
