package com.ktcloud.travelplanner.global.security

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.global.logging.ApplicationLogger
import com.ktcloud.travelplanner.global.logging.RequestIdGenerator
import com.ktcloud.travelplanner.global.logging.RequestLoggingFilter
import com.ktcloud.travelplanner.global.logging.RequestRouteResolver
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.boot.test.context.TestConfiguration
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Import
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.test.context.support.WithMockUser
import org.springframework.security.web.SecurityFilterChain
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController
import java.util.UUID

@ActiveProfiles("test")
@WebMvcTest(ApiSecurityTestController::class)
@Import(
	RequestLoggingFilter::class,
	ApiSecurityErrorHandler::class,
	ProtectedSecurityConfiguration::class,
)
class ApiSecurityErrorIntegrationTest(
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
	fun `unauthenticated request returns server id and denied log`() {
		val response = mockMvc.get("/test/security/protected?token=query-secret") {
			header(RequestIdGenerator.HEADER_NAME, "authentication-client-id")
		}
			.andExpect {
				status { isUnauthorized() }
			}
			.andReturn()
			.response

		assertSecurityErrorContract(
			responseStatus = 401,
			responseContent = response.contentAsString,
			responseRequestId = requireNotNull(response.getHeader(RequestIdGenerator.HEADER_NAME)),
			clientRequestId = "authentication-client-id",
			errorCode = "UNAUTHORIZED",
			message = "인증이 필요합니다.",
		)
	}

	@Test
	@WithMockUser(roles = ["USER"])
	fun `unauthorized role returns server id and denied log`() {
		val response = mockMvc.get("/test/security/admin") {
			header(RequestIdGenerator.HEADER_NAME, "authorization-client-id")
		}
			.andExpect {
				status { isForbidden() }
			}
			.andReturn()
			.response

		assertSecurityErrorContract(
			responseStatus = 403,
			responseContent = response.contentAsString,
			responseRequestId = requireNotNull(response.getHeader(RequestIdGenerator.HEADER_NAME)),
			clientRequestId = "authorization-client-id",
			errorCode = "ACCESS_DENIED",
			message = "접근 권한이 없습니다.",
		)
	}

	private fun assertSecurityErrorContract(
		responseStatus: Int,
		responseContent: String,
		responseRequestId: String,
		clientRequestId: String,
		errorCode: String,
		message: String,
	) {
		UUID.fromString(responseRequestId)
		assertNotEquals(clientRequestId, responseRequestId)
		val responseBody = objectMapper.readTree(responseContent)
		assertEquals(errorCode, responseBody.path("code").asText())
		assertEquals(message, responseBody.path("message").asText())
		assertEquals(responseRequestId, responseBody.path("requestId").asText())
		assertFalse(responseBody.has("fieldErrors"))

		val completionLog = logAppender.list.single()
		val keyValues = completionLog.keyValues()
		val loggedValues = "${completionLog.formattedMessage} ${completionLog.mdcPropertyMap} $keyValues"
		assertEquals(Level.WARN, completionLog.level)
		assertEquals(responseRequestId, completionLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, keyValues["route"])
		assertEquals(responseStatus, keyValues["status"])
		assertEquals("DENIED", keyValues["outcome"])
		assertEquals(errorCode, keyValues["errorCode"])
		assertFalse(loggedValues.contains(clientRequestId))
		assertFalse(loggedValues.contains("query-secret"))
	}

	private fun ILoggingEvent.keyValues(): Map<String, Any> =
		keyValuePairs.associate { it.key to it.value }
}

@RestController
@RequestMapping("/test/security")
class ApiSecurityTestController {
	@GetMapping("/protected")
	fun protectedEndpoint(): String = "protected"

	@GetMapping("/admin")
	fun adminEndpoint(): String = "admin"
}

@TestConfiguration(proxyBeanMethods = false)
class ProtectedSecurityConfiguration {
	@Bean
	fun protectedSecurityFilterChain(
		http: HttpSecurity,
		apiSecurityErrorHandler: ApiSecurityErrorHandler,
	): SecurityFilterChain {
		http
			.securityMatcher("/test/security/**")
			.csrf { it.disable() }
			.exceptionHandling {
				it.authenticationEntryPoint(apiSecurityErrorHandler)
					.accessDeniedHandler(apiSecurityErrorHandler)
			}
			.authorizeHttpRequests {
				it.requestMatchers("/test/security/admin").hasRole("ADMIN")
					.anyRequest().authenticated()
			}
		return http.build()
	}
}
