package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.Level
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

	private val requestLogger = LoggerFactory.getLogger(RequestLoggingFilter::class.java) as Logger
	private val logAppender = ListAppender<ILoggingEvent>()
	private var previousLevel: Level? = null

	@BeforeEach
	fun attachLogAppender() {
		previousLevel = requestLogger.level
		requestLogger.level = Level.INFO
		logAppender.start()
		requestLogger.addAppender(logAppender)
	}

	@AfterEach
	fun detachLogAppender() {
		requestLogger.detachAppender(logAppender)
		requestLogger.level = previousLevel
		logAppender.stop()
		MDC.remove(RequestIdGenerator.MDC_KEY)
	}

	@Test
	fun `valid request id is returned and included in completion log`() {
		mockMvc.get("/api/ping?code=oauth-secret") {
			header(RequestIdGenerator.HEADER_NAME, "frontend-request-123")
		}
			.andExpect {
				status { isOk() }
				header { string(RequestIdGenerator.HEADER_NAME, "frontend-request-123") }
			}

		val completionLog = logAppender.list.single { it.formattedMessage.startsWith("request completed") }
		assertEquals(
			"frontend-request-123",
			completionLog.mdcPropertyMap[RequestIdGenerator.MDC_KEY],
		)
		assertEquals("/api/ping", completionLog.mdcPropertyMap["path"])
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))
	}

	@Test
	fun `invalid request id is replaced and returned`() {
		val response = mockMvc.get("/api/ping") {
			header(RequestIdGenerator.HEADER_NAME, "invalid request id")
		}
			.andExpect {
				status { isOk() }
			}
			.andReturn()
			.response

		val generatedRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(generatedRequestId)
		assertEquals(
			generatedRequestId,
			logAppender.list.single { it.formattedMessage.startsWith("request completed") }
				.mdcPropertyMap[RequestIdGenerator.MDC_KEY],
		)
	}
}
