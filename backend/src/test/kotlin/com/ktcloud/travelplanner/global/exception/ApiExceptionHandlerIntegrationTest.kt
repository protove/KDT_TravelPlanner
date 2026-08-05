package com.ktcloud.travelplanner.global.exception

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.global.logging.ApplicationLogger
import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import com.ktcloud.travelplanner.global.logging.RequestLoggingFilter
import com.ktcloud.travelplanner.global.response.ApiResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Import
import org.springframework.http.MediaType
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.web.SecurityFilterChain
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@ActiveProfiles("test")
@WebMvcTest(ApiExceptionTestController::class)
@Import(
	ApiExceptionHandler::class,
	RequestLoggingFilter::class,
	PermitAllSecurityConfiguration::class,
)
class ApiExceptionHandlerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val objectMapper: ObjectMapper,
) {
	private val applicationLogger = LoggerFactory.getLogger(ApplicationLogger::class.java) as Logger
	private val logAppender = ListAppender<ILoggingEvent>()
	private var previousLevel: Level? = null

	@BeforeEach
	fun attachLogAppender() {
		previousLevel = applicationLogger.level
		applicationLogger.level = Level.TRACE
		logAppender.start()
		applicationLogger.addAppender(logAppender)
	}

	@AfterEach
	fun detachLogAppender() {
		applicationLogger.detachAppender(logAppender)
		applicationLogger.level = previousLevel
		logAppender.stop()
	}

	@Test
	fun `validation errors are sorted and use the server request id`() {
		val response = mockMvc.post("/test/errors/validation") {
			header(RequestIdGenerator.HEADER_NAME, "validation-client-id")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"","city":""}"""
		}
			.andExpect {
				status { isBadRequest() }
			}
			.andReturn()
			.response

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(responseRequestId)
		assertNotEquals("validation-client-id", responseRequestId)
		val responseBody = objectMapper.readTree(response.contentAsString)
		assertEquals("VALIDATION_ERROR", responseBody.path("code").asText())
		assertEquals("요청값이 올바르지 않습니다.", responseBody.path("message").asText())
		assertEquals(responseRequestId, responseBody.path("requestId").asText())
		assertEquals("city", responseBody.path("fieldErrors").path(0).path("field").asText())
		assertEquals("title", responseBody.path("fieldErrors").path(1).path("field").asText())

		val completionLog = logAppender.list.single()
		assertEquals(Level.INFO, completionLog.level)
		assertEquals("VALIDATION_ERROR", completionLog.keyValues()["errorCode"])
		assertEquals(responseRequestId, completionLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
	}

	@Test
	fun `malformed JSON uses the common error and safe log contract`() {
		val response = mockMvc.post("/test/errors/validation") {
			header(RequestIdGenerator.HEADER_NAME, "json-client-id")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"broken""""
		}
			.andExpect {
				status { isBadRequest() }
			}
			.andReturn()
			.response

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		val responseBody = objectMapper.readTree(response.contentAsString)
		assertEquals("MALFORMED_JSON", responseBody.path("code").asText())
		assertEquals(responseRequestId, responseBody.path("requestId").asText())
		assertFalse(responseBody.has("fieldErrors"))
		assertEquals("MALFORMED_JSON", logAppender.list.single().keyValues()["errorCode"])
	}

	@Test
	fun `domain not found and conflict errors log at info without failure details`() {
		mockMvc.get("/test/errors/not-found")
			.andExpect {
				status { isNotFound() }
			}

		mockMvc.get("/test/errors/conflict")
			.andExpect {
				status { isConflict() }
			}

		assertEquals(2, logAppender.list.size)
		assertTrue(logAppender.list.all { it.level == Level.INFO })
		assertEquals(
			setOf("RESOURCE_NOT_FOUND", "CONFLICT"),
			logAppender.list.map { it.keyValues()["errorCode"] }.toSet(),
		)
		assertTrue(logAppender.list.all { it.keyValues()["event"] == "HTTP_REQUEST_COMPLETED" })
	}

	@Test
	fun `unexpected error preserves the response contract and logs only safe failure fields`() {
		val response = mockMvc.get("/test/errors/unexpected") {
			header(RequestIdGenerator.HEADER_NAME, "unexpected-client-id")
		}
			.andExpect {
				status { isInternalServerError() }
			}
			.andReturn()
			.response

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(responseRequestId)
		assertNotEquals("unexpected-client-id", responseRequestId)
		val responseBody = objectMapper.readTree(response.contentAsString)
		assertEquals("INTERNAL_SERVER_ERROR", responseBody.path("code").asText())
		assertEquals("서버 내부 오류가 발생했습니다.", responseBody.path("message").asText())
		assertEquals(responseRequestId, responseBody.path("requestId").asText())
		assertFalse(response.contentAsString.contains("database-password"))

		assertEquals(2, logAppender.list.size)
		val failureLog = logAppender.list.single { it.keyValues()["event"] == "UNEXPECTED_REQUEST_FAILURE" }
		val completionLog = logAppender.list.single { it.keyValues()["event"] == "HTTP_REQUEST_COMPLETED" }
		val failureValues = failureLog.keyValues()
		val allLoggedValues = logAppender.list.joinToString { "${it.formattedMessage} ${it.keyValues()}" }

		assertEquals(responseRequestId, failureLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertEquals(IllegalStateException::class.java.name, failureValues["errorType"])
		assertTrue((failureValues["errorFingerprint"] as String).matches(Regex("^[0-9a-f]{64}$")))
		assertTrue((failureValues["errorFrames"] as List<*>).size <= 5)
		assertNull(failureLog.throwableProxy)
		assertEquals(responseRequestId, completionLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertEquals("/test/errors/unexpected", completionLog.keyValues()["route"])
		assertEquals("INTERNAL_SERVER_ERROR", completionLog.keyValues()["errorCode"])
		assertNull(completionLog.throwableProxy)
		assertFalse(allLoggedValues.contains("database-password"))
		assertFalse(allLoggedValues.contains("unexpected-client-id"))
	}

	private fun ILoggingEvent.keyValues(): Map<String, Any> =
		keyValuePairs.associate { it.key to it.value }
}

@RestController
@RequestMapping("/test/errors")
class ApiExceptionTestController {
	@PostMapping("/validation")
	fun validate(
		@Valid @RequestBody request: ValidationRequest,
	): ApiResponse<ValidationRequest> = ApiResponse.success(request)

	@GetMapping("/not-found")
	fun notFound(): ApiResponse<Unit> = throw DomainException(ErrorCode.RESOURCE_NOT_FOUND)

	@GetMapping("/conflict")
	fun conflict(): ApiResponse<Unit> = throw DomainException(ErrorCode.CONFLICT)

	@GetMapping("/unexpected")
	fun unexpected(): ApiResponse<Unit> = throw IllegalStateException("database-password")
}

data class ValidationRequest(
	@field:NotBlank val title: String,
	@field:NotBlank val city: String,
)

@TestConfiguration(proxyBeanMethods = false)
class PermitAllSecurityConfiguration {
	@Bean
	fun testSecurityFilterChain(http: HttpSecurity): SecurityFilterChain {
		http
			.csrf { it.disable() }
			.authorizeHttpRequests { it.anyRequest().permitAll() }
		return http.build()
	}
}
