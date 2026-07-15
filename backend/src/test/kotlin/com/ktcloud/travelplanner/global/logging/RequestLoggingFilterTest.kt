package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import jakarta.servlet.FilterChain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.CsvSource
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.http.HttpHeaders
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class RequestLoggingFilterTest {

	private val requestLogger = LoggerFactory.getLogger(RequestLoggingFilter::class.java) as Logger
	private val logAppender = ListAppender<ILoggingEvent>()
	private val requestLoggingFilter = RequestLoggingFilter(RequestIdGenerator())

	@BeforeEach
	fun attachLogAppender() {
		logAppender.start()
		requestLogger.addAppender(logAppender)
	}

	@AfterEach
	fun detachLogAppender() {
		requestLogger.detachAppender(logAppender)
		logAppender.stop()
		MDC.remove(RequestIdGenerator.MDC_KEY)
	}

	@ParameterizedTest
	@CsvSource(
		"200, INFO",
		"302, INFO",
		"400, WARN",
		"404, WARN",
		"500, ERROR",
		"503, ERROR",
	)
	fun `HTTP status selects request log level`(httpStatus: Int, expectedLevel: String) {
		assertEquals(expectedLevel, RequestLogLevelPolicy.resolve(httpStatus).name)
	}

	@Test
	fun `request id is available during request and removed afterwards`() {
		val request = createSensitiveRequest()
		val response = MockHttpServletResponse()
		var requestIdDuringFilter: String? = null
		val filterChain = FilterChain { _, servletResponse ->
			requestIdDuringFilter = MDC.get(RequestIdGenerator.MDC_KEY)
			(servletResponse as MockHttpServletResponse).status = 404
		}

		requestLoggingFilter.doFilter(request, response, filterChain)

		assertEquals("safe-request-id", requestIdDuringFilter)
		assertEquals("safe-request-id", response.getHeader(RequestIdGenerator.HEADER_NAME))
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))
		assertEquals(Level.WARN, logAppender.list.single().level)
		assertEquals("safe-request-id", logAppender.list.single().mdcPropertyMap[RequestIdGenerator.MDC_KEY])
	}

	@Test
	fun `request completion log excludes query headers cookies and body`() {
		val request = createSensitiveRequest()
		val response = MockHttpServletResponse()

		requestLoggingFilter.doFilter(request, response, FilterChain { _, _ -> })

		val logEvent = logAppender.list.single()
		val loggedValues = buildString {
			append(logEvent.formattedMessage)
			logEvent.mdcPropertyMap.forEach { (key, value) ->
				append(' ')
				append(key)
				append('=')
				append(value)
			}
		}

		assertEquals("/api/ping", logEvent.mdcPropertyMap["path"])
		assertFalse(loggedValues.contains("oauth-secret"))
		assertFalse(loggedValues.contains("jwt-secret"))
		assertFalse(loggedValues.contains("cookie-secret"))
		assertFalse(loggedValues.contains("password-secret"))
	}

	@Test
	fun `unexpected failure is logged once as error without stack trace`() {
		val request = MockHttpServletRequest("GET", "/api/failure")
		val response = MockHttpServletResponse()
		val failure = IllegalStateException("internal-secret")

		assertThrows(IllegalStateException::class.java) {
			requestLoggingFilter.doFilter(request, response, FilterChain { _, _ -> throw failure })
		}

		val logEvent = logAppender.list.single()
		assertEquals(Level.ERROR, logEvent.level)
		assertEquals("500", logEvent.mdcPropertyMap["status"])
		assertNull(logEvent.throwableProxy)
		assertFalse(logEvent.formattedMessage.contains("internal-secret"))
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))
	}

	private fun createSensitiveRequest(): MockHttpServletRequest =
		MockHttpServletRequest("POST", "/api/ping").apply {
			addHeader(RequestIdGenerator.HEADER_NAME, "safe-request-id")
			addHeader(HttpHeaders.AUTHORIZATION, "Bearer jwt-secret")
			addHeader(HttpHeaders.COOKIE, "refreshToken=cookie-secret")
			queryString = "code=oauth-secret&state=state-secret"
			setContent("{\"password\":\"password-secret\"}".toByteArray())
		}
}
