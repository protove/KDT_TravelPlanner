package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import com.ktcloud.travelplanner.PingController
import com.ktcloud.travelplanner.WebConfig
import com.ktcloud.travelplanner.global.security.ApiSecurityErrorHandler
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.global.security.SecurityConfig
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.context.annotation.Import
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import java.util.UUID

@ActiveProfiles("test")
@WebMvcTest(PingController::class)
@Import(
	WebConfig::class,
	RequestLoggingFilter::class,
	ApiSecurityErrorHandler::class,
	SecurityConfig::class,
)
class RequestLoggingIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
) {
	@MockitoBean
	private lateinit var jwtTokenService: JwtTokenService

	@MockitoBean
	private lateinit var userRepository: UserRepository

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
		MDC.clear()
	}

	@Test
	fun `mapped request receives server id and logs only the route template`() {
		val response = mockMvc.get("/api/ping?code=oauth-secret") {
			header(RequestIdGenerator.HEADER_NAME, CLIENT_REQUEST_ID)
		}
			.andExpect {
				status { isOk() }
			}
			.andReturn()
			.response

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(responseRequestId)
		assertNotEquals(CLIENT_REQUEST_ID, responseRequestId)

		val completionLog = logAppender.list.single { it.keyValues()["event"] == "HTTP_REQUEST_COMPLETED" }
		val keyValues = completionLog.keyValues()
		val loggedValues = "${completionLog.formattedMessage} ${completionLog.mdcPropertyMap} $keyValues"

		assertEquals(responseRequestId, completionLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertEquals("/api/ping", keyValues["route"])
		assertEquals(200, keyValues["status"])
		assertEquals("SUCCESS", keyValues["outcome"])
		assertFalse(loggedValues.contains(CLIENT_REQUEST_ID))
		assertFalse(loggedValues.contains("oauth-secret"))
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))
	}

	@Test
	fun `unmapped request never logs its raw path`() {
		val response = mockMvc.get("/not-mapped/$RAW_PATH_SENTINEL?token=query-secret")
			.andExpect {
				status { isNotFound() }
			}
			.andReturn()
			.response

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(responseRequestId)
		val completionLog = logAppender.list.single { it.keyValues()["event"] == "HTTP_REQUEST_COMPLETED" }
		val keyValues = completionLog.keyValues()
		val loggedValues = "${completionLog.formattedMessage} ${completionLog.mdcPropertyMap} $keyValues"

		assertEquals(Level.INFO, completionLog.level)
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, keyValues["route"])
		assertEquals(404, keyValues["status"])
		assertFalse(loggedValues.contains(RAW_PATH_SENTINEL))
		assertFalse(loggedValues.contains("query-secret"))
	}

	private fun ILoggingEvent.keyValues(): Map<String, Any> =
		keyValuePairs.associate { it.key to it.value }

	companion object {
		private const val CLIENT_REQUEST_ID = "frontend-request-id-sentinel"
		private const val RAW_PATH_SENTINEL = "018f1ed0-dead-beef-acde-0242ac120002"
	}
}
