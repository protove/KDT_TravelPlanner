package com.ktcloud.travelplanner.global.exception

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import com.ktcloud.travelplanner.global.logging.RequestLoggingFilter
import com.ktcloud.travelplanner.global.response.ApiResponse
import jakarta.validation.Valid
import jakarta.validation.constraints.NotBlank
import org.hamcrest.Matchers.containsString
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.not
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
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

@ActiveProfiles("test")
@WebMvcTest(ApiExceptionTestController::class)
@Import(
	ApiExceptionHandler::class,
	RequestLoggingFilter::class,
	PermitAllSecurityConfiguration::class,
)
class ApiExceptionHandlerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
) {
	private val exceptionLogger = LoggerFactory.getLogger(ApiExceptionHandler::class.java) as Logger
	private val logAppender = ListAppender<ILoggingEvent>()
	private var previousLevel: Level? = null

	@BeforeEach
	fun attachLogAppender() {
		previousLevel = exceptionLogger.level
		exceptionLogger.level = Level.ERROR
		logAppender.start()
		exceptionLogger.addAppender(logAppender)
	}

	@AfterEach
	fun detachLogAppender() {
		exceptionLogger.detachAppender(logAppender)
		exceptionLogger.level = previousLevel
		logAppender.stop()
	}

	@Test
	fun `validation errors are sorted and include matching request id`() {
		mockMvc.post("/test/errors/validation") {
			header(RequestIdGenerator.HEADER_NAME, "validation-request")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"","city":""}"""
		}
			.andExpect {
				status { isBadRequest() }
				header { string(RequestIdGenerator.HEADER_NAME, "validation-request") }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.message", equalTo("요청값이 올바르지 않습니다."))
				jsonPath("$.requestId", equalTo("validation-request"))
				jsonPath("$.fieldErrors[0].field", equalTo("city"))
				jsonPath("$.fieldErrors[1].field", equalTo("title"))
			}

		assertTrue(logAppender.list.isEmpty())
	}

	@Test
	fun `malformed JSON uses the common error contract`() {
		mockMvc.post("/test/errors/validation") {
			header(RequestIdGenerator.HEADER_NAME, "json-request")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"broken""""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("MALFORMED_JSON"))
				jsonPath("$.requestId", equalTo("json-request"))
				jsonPath("$.fieldErrors") { doesNotExist() }
			}
	}

	@Test
	fun `domain not found and conflict errors map without stack traces`() {
		mockMvc.get("/test/errors/not-found")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}

		mockMvc.get("/test/errors/conflict")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}

		assertTrue(logAppender.list.isEmpty())
	}

	@Test
	fun `unexpected error hides internals and logs one stack trace with request id`() {
		mockMvc.get("/test/errors/unexpected") {
			header(RequestIdGenerator.HEADER_NAME, "error-request")
		}
			.andExpect {
				status { isInternalServerError() }
				header { string(RequestIdGenerator.HEADER_NAME, "error-request") }
				jsonPath("$.code", equalTo("INTERNAL_SERVER_ERROR"))
				jsonPath("$.message", equalTo("서버 내부 오류가 발생했습니다."))
				jsonPath("$.requestId", equalTo("error-request"))
				content { string(not(containsString("database-password"))) }
			}

		val errorLog = logAppender.list.single()
		assertEquals("error-request", errorLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertNotNull(errorLog.throwableProxy)
	}

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
