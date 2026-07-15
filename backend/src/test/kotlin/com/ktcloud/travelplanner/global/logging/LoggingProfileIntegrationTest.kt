package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.LoggerContext
import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.MethodOrderer.OrderAnnotation
import org.junit.jupiter.api.Order
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestMethodOrder
import org.junit.jupiter.api.extension.ExtendWith
import org.slf4j.LoggerFactory
import org.springframework.boot.WebApplicationType
import org.springframework.boot.builder.SpringApplicationBuilder
import org.springframework.boot.test.system.CapturedOutput
import org.springframework.boot.test.system.OutputCaptureExtension
import org.springframework.context.annotation.Configuration
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.readLines

@ExtendWith(OutputCaptureExtension::class)
@TestMethodOrder(OrderAnnotation::class)
class LoggingProfileIntegrationTest {

	private val objectMapper = ObjectMapper()

	@BeforeEach
	@AfterEach
	fun resetLoggingContext() {
		(LoggerFactory.getILoggerFactory() as LoggerContext).reset()
	}

	@Test
	@Order(1)
	fun `dev profile writes readable text to stdout and rolling file`(capturedOutput: CapturedOutput) {
		val logFile = Files.createTempDirectory("travel-planner-dev-log").resolve("travel-planner.log")

		runLoggingProbe("dev", logFile, DEV_MARKER)

		assertTrue(capturedOutput.out.lineSequence().any { it.contains(DEV_MARKER) && !it.trim().startsWith("{") })
		assertTrue(logFile.readLines().any { it.contains(DEV_MARKER) && !it.trim().startsWith("{") })
	}

	@Test
	@Order(2)
	fun `prod profile writes ECS JSON to stdout and rolling file`(capturedOutput: CapturedOutput) {
		val logFile = Files.createTempDirectory("travel-planner-prod-log").resolve("travel-planner.log")

		runLoggingProbe("prod", logFile, PROD_MARKER)

		val consoleLog = capturedOutput.out.lineSequence().first { it.contains(PROD_MARKER) }
		val fileLog = logFile.readLines().first { it.contains(PROD_MARKER) }
		val consoleJson = objectMapper.readTree(consoleLog)
		val fileJson = objectMapper.readTree(fileLog)

		assertEquals(PROD_MARKER, consoleJson.path("message").asText())
		assertEquals("travel-planner-backend", consoleJson.path("service").path("name").asText())
		assertEquals(PROD_MARKER, fileJson.path("message").asText())
		assertEquals("8.11", fileJson.path("ecs").path("version").asText())
	}

	@Test
	@Order(3)
	fun `test profile keeps console only`() {
		val context = SpringApplicationBuilder(LoggingProbeConfiguration::class.java)
			.web(WebApplicationType.NONE)
			.registerShutdownHook(false)
			.run(
				"--spring.main.banner-mode=off",
				"--spring.profiles.active=test",
			)

		try {
			assertNull(context.environment.getProperty("logging.file.name"))
			assertFalse(context.environment.containsProperty("logging.structured.format.file"))
		} finally {
			context.close()
		}
	}

	private fun runLoggingProbe(profile: String, logFile: Path, marker: String) {
		val context = SpringApplicationBuilder(LoggingProbeConfiguration::class.java)
			.web(WebApplicationType.NONE)
			.registerShutdownHook(false)
			.run(
				"--spring.application.name=travel-planner-backend",
				"--spring.main.banner-mode=off",
				"--spring.profiles.active=$profile",
				"--logging.file.name=$logFile",
			)

		try {
			LoggerFactory.getLogger(LOGGER_NAME).info(marker)
		} finally {
			context.close()
		}
	}

	@Configuration(proxyBeanMethods = false)
	private class LoggingProbeConfiguration

	companion object {
		private const val LOGGER_NAME = "travel-planner-logging-probe"
		private const val DEV_MARKER = "dev-profile-log-marker"
		private const val PROD_MARKER = "prod-profile-log-marker"
	}
}
