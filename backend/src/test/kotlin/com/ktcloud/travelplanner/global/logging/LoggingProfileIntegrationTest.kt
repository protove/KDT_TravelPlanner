package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.LoggerContext
import com.fasterxml.jackson.databind.JsonNode
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
import org.slf4j.MDC
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
		MDC.clear()
		(LoggerFactory.getILoggerFactory() as LoggerContext).reset()
	}

	@Test
	@Order(1)
	fun `dev profile writes readable stdout and ECS JSON rolling file`(capturedOutput: CapturedOutput) {
		val logFile = Files.createTempDirectory("travel-planner-dev-log").resolve("travel-planner.log")

		val loggingProperties = runLoggingProbe("dev", logFile, DEV_MARKER)

		assertTrue(capturedOutput.out.lineSequence().any { it.contains(DEV_MARKER) && !it.trim().startsWith("{") })
		assertRollingPolicy(loggingProperties)
		assertEquals("50", loggingProperties.errorFrameLimit)
		val fileLog = logFile.readLines().first { it.contains(DEV_MARKER) }
		val fileJson = objectMapper.readTree(fileLog)

		assertEquals(DEV_MARKER, fileJson.path("message").asText())
		assertEquals(
			"travel-planner-backend",
			fileJson.path("service").path("name").asText(),
			fileJson.toPrettyString(),
		)
		assertEquals("dev", fileJson.path("service").path("environment").asText())
		assertEquals("8.11", fileJson.path("ecs").path("version").asText())
		assertRequestCompletedJson(logFile)
	}

	@Test
	@Order(2)
	fun `prod profile writes ECS JSON rolling file without application stdout`(capturedOutput: CapturedOutput) {
		val logFile = Files.createTempDirectory("travel-planner-prod-log").resolve("travel-planner.log")

		val loggingProperties = runLoggingProbe("prod", logFile, PROD_MARKER)

		val fileLog = logFile.readLines().first { it.contains(PROD_MARKER) }
		val fileJson = objectMapper.readTree(fileLog)

		assertFalse(capturedOutput.out.lineSequence().any { it.contains(PROD_MARKER) })
		assertRollingPolicy(loggingProperties)
		assertEquals("5", loggingProperties.errorFrameLimit)
		assertEquals(PROD_MARKER, fileJson.path("message").asText())
		assertEquals(
			"travel-planner-backend",
			fileJson.path("service").path("name").asText(),
			fileJson.toPrettyString(),
		)
		assertEquals("prod", fileJson.path("service").path("environment").asText())
		assertEquals("8.11", fileJson.path("ecs").path("version").asText())
		assertRequestCompletedJson(logFile)
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
			assertEquals("5", context.environment.getProperty("app.logging.error-frame-limit"))

			val rootLogger = (LoggerFactory.getILoggerFactory() as LoggerContext)
				.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME)
			val appenderNames = rootLogger.iteratorForAppenders().asSequence().map { it.name }.toSet()
			assertEquals(setOf("CONSOLE"), appenderNames)
		} finally {
			context.close()
		}
	}

	private fun runLoggingProbe(profile: String, logFile: Path, marker: String): LoggingProperties {
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
			MDC.put(RequestIdGenerator.MDC_KEY, REQUEST_ID)
			MDC.put(FORBIDDEN_MDC_KEY, FORBIDDEN_MDC_VALUE)
			ApplicationLogger.logRequestCompleted(
				RequestCompletedLog(
					requestId = REQUEST_ID,
					method = "GET",
					route = "/api/travels/{travelId}",
					status = 200,
					durationMs = 12,
					outcome = LogOutcome.SUCCESS,
				),
				RequestLogLevel.INFO,
			)
			ApplicationLogger.logUnexpectedFailure(
				UnexpectedFailureLog(
					requestId = REQUEST_ID,
					summary = SafeExceptionSummary(
						errorType = IllegalStateException::class.java.name,
						errorFingerprint = ERROR_FINGERPRINT,
						errorFrames = listOf(ERROR_FRAME),
					),
				),
			)
			return LoggingProperties(
				maxFileSize = context.environment.getProperty("logging.logback.rollingpolicy.max-file-size"),
				maxHistory = context.environment.getProperty("logging.logback.rollingpolicy.max-history"),
				totalSizeCap = context.environment.getProperty("logging.logback.rollingpolicy.total-size-cap"),
				errorFrameLimit = context.environment.getProperty("app.logging.error-frame-limit"),
				generatedPasswordLoggerLevel = context.environment.getProperty(
					"logging.level.org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration",
				),
			)
		} finally {
			MDC.clear()
			context.close()
		}
	}

	private fun assertRollingPolicy(loggingProperties: LoggingProperties) {
		assertEquals("20MB", loggingProperties.maxFileSize)
		assertEquals("7", loggingProperties.maxHistory)
		assertEquals("500MB", loggingProperties.totalSizeCap)
		assertEquals("OFF", loggingProperties.generatedPasswordLoggerLevel)
	}

	private fun assertRequestCompletedJson(logFile: Path) {
		val requestLog = logFile.readLines().first { it.contains("HTTP_REQUEST_COMPLETED") }
		val requestJson = objectMapper.readTree(requestLog)

		assertEquals("HTTP_REQUEST_COMPLETED", requestJson.path("message").asText())
		assertEquals("HTTP_REQUEST_COMPLETED", requestJson.path("event").asText())
		assertEquals(REQUEST_ID, requestJson.path("requestId").asText())
		assertEquals("GET", requestJson.path("method").asText())
		assertEquals("/api/travels/{travelId}", requestJson.path("route").asText())
		assertTrue(requestJson.path("status").isIntegralNumber)
		assertEquals(200, requestJson.path("status").intValue())
		assertTrue(requestJson.path("durationMs").isIntegralNumber)
		assertEquals(12, requestJson.path("durationMs").longValue())
		assertEquals("SUCCESS", requestJson.path("outcome").asText())
		assertFalse(requestLog.contains(FORBIDDEN_MDC_KEY))
		assertFalse(requestLog.contains(FORBIDDEN_MDC_VALUE))
		assertEquals(EXPECTED_REQUEST_LOG_LEAF_PATHS, collectLeafPaths(requestJson))

		val failureLog = logFile.readLines().first { it.contains("UNEXPECTED_REQUEST_FAILURE") }
		val failureJson = objectMapper.readTree(failureLog)

		assertEquals("UNEXPECTED_REQUEST_FAILURE", failureJson.path("message").asText())
		assertEquals("UNEXPECTED_REQUEST_FAILURE", failureJson.path("event").asText())
		assertEquals(REQUEST_ID, failureJson.path("requestId").asText())
		assertEquals(IllegalStateException::class.java.name, failureJson.path("errorType").asText())
		assertEquals(ERROR_FINGERPRINT, failureJson.path("errorFingerprint").asText())
		assertTrue(failureJson.path("errorFrames").isArray)
		assertEquals(listOf(ERROR_FRAME), failureJson.path("errorFrames").map(JsonNode::asText))
		assertFalse(failureLog.contains(FORBIDDEN_MDC_KEY))
		assertFalse(failureLog.contains(FORBIDDEN_MDC_VALUE))
		assertEquals(EXPECTED_FAILURE_LOG_LEAF_PATHS, collectLeafPaths(failureJson))
	}

	private fun collectLeafPaths(node: JsonNode, prefix: String = ""): Set<String> = when {
		node.isObject -> node.properties().asSequence().flatMap { (fieldName, fieldValue) ->
			val fieldPath = if (prefix.isEmpty()) fieldName else "$prefix.$fieldName"
			collectLeafPaths(fieldValue, fieldPath).asSequence()
		}.toSet()
		else -> setOf(prefix)
	}

	private data class LoggingProperties(
		val maxFileSize: String?,
		val maxHistory: String?,
		val totalSizeCap: String?,
		val errorFrameLimit: String?,
		val generatedPasswordLoggerLevel: String?,
	)

	@Configuration(proxyBeanMethods = false)
	private class LoggingProbeConfiguration

	companion object {
		private const val LOGGER_NAME = "com.ktcloud.travelplanner.global.logging.ApplicationLogger"
		private const val DEV_MARKER = "dev-profile-log-marker"
		private const val PROD_MARKER = "prod-profile-log-marker"
		private const val REQUEST_ID = "2b8e2730-8539-4c06-856d-abe49103a9c5"
		private const val ERROR_FINGERPRINT =
			"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
		private const val ERROR_FRAME = "com.ktcloud.travelplanner.travel.service.TravelService#load"
		private const val FORBIDDEN_MDC_KEY = "unexpectedMdcField"
		private const val FORBIDDEN_MDC_VALUE = "mdc-secret-sentinel"
		private val EXPECTED_REQUEST_LOG_LEAF_PATHS = setOf(
			"@timestamp",
			"ecs.version",
			"log.level",
			"log.logger",
			"process.pid",
			"process.thread.name",
			"service.name",
			"service.environment",
			"message",
			"event",
			"requestId",
			"method",
			"route",
			"status",
			"durationMs",
			"outcome",
		)
		private val EXPECTED_FAILURE_LOG_LEAF_PATHS = setOf(
			"@timestamp",
			"ecs.version",
			"log.level",
			"log.logger",
			"process.pid",
			"process.thread.name",
			"service.name",
			"service.environment",
			"message",
			"event",
			"requestId",
			"errorType",
			"errorFingerprint",
			"errorFrames",
		)
	}
}
