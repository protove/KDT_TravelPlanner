package com.ktcloud.travelplanner.global.logging

import ch.qos.logback.classic.Level
import ch.qos.logback.classic.Logger
import ch.qos.logback.classic.spi.ILoggingEvent
import ch.qos.logback.core.read.ListAppender
import com.ktcloud.travelplanner.global.exception.ErrorCode
import jakarta.servlet.FilterChain
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.http.HttpHeaders
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse
import org.springframework.web.method.HandlerMethod
import org.springframework.web.servlet.HandlerMapping
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class RequestLoggingFilterTest {

	private val applicationLogger = LoggerFactory.getLogger(ApplicationLogger::class.java) as Logger
	private val logAppender = ListAppender<ILoggingEvent>()
	private val requestLoggingFilter = RequestLoggingFilter(5)
	private var previousLevel: Level? = null

	@BeforeEach
	fun attachLogAppender() {
		previousLevel = applicationLogger.level
		applicationLogger.level = Level.TRACE
		MDC.clear()
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
	fun `status and error code select the exact level and outcome`() {
		assertDecision(200, null, RequestLogLevel.INFO, LogOutcome.SUCCESS)
		assertDecision(302, null, RequestLogLevel.INFO, LogOutcome.SUCCESS)
		assertDecision(400, null, RequestLogLevel.INFO, LogOutcome.FAILURE)
		assertDecision(404, null, RequestLogLevel.INFO, LogOutcome.FAILURE)
		assertDecision(409, null, RequestLogLevel.INFO, LogOutcome.FAILURE)
		assertDecision(404, ErrorCode.RESOURCE_NOT_FOUND, RequestLogLevel.INFO, LogOutcome.FAILURE)
		assertDecision(409, ErrorCode.CONFLICT, RequestLogLevel.INFO, LogOutcome.FAILURE)
		assertDecision(401, ErrorCode.UNAUTHORIZED, RequestLogLevel.WARN, LogOutcome.DENIED)
		assertDecision(403, ErrorCode.ACCESS_DENIED, RequestLogLevel.WARN, LogOutcome.DENIED)
		assertDecision(429, null, RequestLogLevel.WARN, LogOutcome.FAILURE)
		assertDecision(503, ErrorCode.GOOGLE_PLACES_QUOTA_EXCEEDED, RequestLogLevel.WARN, LogOutcome.FAILURE)
		assertDecision(504, ErrorCode.GOOGLE_ROUTES_TIMEOUT, RequestLogLevel.WARN, LogOutcome.FAILURE)
		assertDecision(418, null, RequestLogLevel.WARN, LogOutcome.FAILURE)
		assertDecision(502, ErrorCode.OAUTH_PROVIDER_ERROR, RequestLogLevel.ERROR, LogOutcome.FAILURE)
		assertDecision(500, ErrorCode.INTERNAL_SERVER_ERROR, RequestLogLevel.ERROR, LogOutcome.FAILURE)
	}

	@Test
	fun `server request id is available during request and client id is ignored`() {
		val request = createSensitiveRequest()
		val response = MockHttpServletResponse()
		var requestIdDuringFilter: String? = null
		val filterChain = FilterChain { servletRequest, servletResponse ->
			requestIdDuringFilter = MDC.get(RequestIdGenerator.MDC_KEY)
			RequestLoggingContext.setErrorCode(
				servletRequest as MockHttpServletRequest,
				ErrorCode.RESOURCE_NOT_FOUND,
			)
			(servletResponse as MockHttpServletResponse).status = 404
		}

		requestLoggingFilter.doFilter(request, response, filterChain)

		val responseRequestId = response.getHeader(RequestIdGenerator.HEADER_NAME)
		UUID.fromString(responseRequestId)
		assertNotEquals(CLIENT_REQUEST_ID, responseRequestId)
		assertEquals(responseRequestId, requestIdDuringFilter)
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))

		val logEvent = logAppender.list.single()
		val keyValues = logEvent.keyValues()
		assertEquals(Level.INFO, logEvent.level)
		assertEquals(responseRequestId, logEvent.mdcPropertyMap[RequestIdGenerator.MDC_KEY])
		assertEquals(setOf(RequestIdGenerator.MDC_KEY), logEvent.mdcPropertyMap.keys)
		assertEquals("RESOURCE_NOT_FOUND", keyValues["errorCode"])
		assertEquals("FAILURE", keyValues["outcome"])
	}

	@Test
	fun `concurrent requests keep request ids isolated and clear MDC`() {
		val requests = listOf("client-one", "client-two").associateWith { clientRequestId ->
			MockHttpServletRequest("GET", "/actuator/health").apply {
				addHeader(RequestIdGenerator.HEADER_NAME, clientRequestId)
			}
		}
		val responses = requests.mapValues { MockHttpServletResponse() }
		val requestIdsDuringFilter = ConcurrentHashMap<String, String>()
		val mdcClearedAfterFilter = ConcurrentHashMap<String, Boolean>()
		val requestsReady = CountDownLatch(requests.size)
		val releaseRequests = CountDownLatch(1)
		val executor = Executors.newFixedThreadPool(requests.size)

		try {
			val futures = requests.map { (clientRequestId, request) ->
				executor.submit {
					requestLoggingFilter.doFilter(
						request,
						responses.getValue(clientRequestId),
						FilterChain { _, _ ->
							requestIdsDuringFilter[clientRequestId] =
								requireNotNull(MDC.get(RequestIdGenerator.MDC_KEY))
							requestsReady.countDown()
							assertTrue(releaseRequests.await(5, TimeUnit.SECONDS))
						},
					)
					mdcClearedAfterFilter[clientRequestId] = MDC.get(RequestIdGenerator.MDC_KEY) == null
				}
			}

			assertTrue(requestsReady.await(5, TimeUnit.SECONDS))
			releaseRequests.countDown()
			futures.forEach { it.get(5, TimeUnit.SECONDS) }
		} finally {
			releaseRequests.countDown()
			executor.shutdownNow()
		}

		assertEquals(requests.keys, requestIdsDuringFilter.keys)
		assertEquals(requests.size, requestIdsDuringFilter.values.toSet().size)
		requestIdsDuringFilter.forEach { (clientRequestId, serverRequestId) ->
			UUID.fromString(serverRequestId)
			assertNotEquals(clientRequestId, serverRequestId)
			assertEquals(serverRequestId, responses.getValue(clientRequestId).getHeader(RequestIdGenerator.HEADER_NAME))
		}
		assertEquals(requests.keys, mdcClearedAfterFilter.keys)
		assertTrue(mdcClearedAfterFilter.values.all { it })
		assertTrue(logAppender.list.isEmpty())
	}

	@Test
	fun `request completion log uses route template and excludes untrusted request data`() {
		val request = createSensitiveRequest()
		val response = MockHttpServletResponse()

		requestLoggingFilter.doFilter(request, response, FilterChain { _, _ -> })

		val logEvent = logAppender.list.single()
		val keyValues = logEvent.keyValues()
		val loggedValues = buildString {
			append(logEvent.formattedMessage)
			append(logEvent.mdcPropertyMap)
			append(keyValues)
		}

		assertEquals("HTTP_REQUEST_COMPLETED", logEvent.formattedMessage)
		assertEquals("HTTP_REQUEST_COMPLETED", keyValues["event"])
		assertEquals("POST", keyValues["method"])
		assertEquals("/api/travels/{travelId}", keyValues["route"])
		assertTrue(keyValues["status"] is Int)
		assertTrue(keyValues["durationMs"] is Long)
		assertFalse(loggedValues.contains(CLIENT_REQUEST_ID))
		assertFalse(loggedValues.contains(RAW_TRAVEL_ID))
		assertFalse(loggedValues.contains("oauth-secret"))
		assertFalse(loggedValues.contains("jwt-secret"))
		assertFalse(loggedValues.contains("cookie-secret"))
		assertFalse(loggedValues.contains("password-secret"))
	}

	@Test
	fun `route resolver requires a safe route template and HandlerMethod`() {
		val request = MockHttpServletRequest("GET", "/raw/path")
		val handlerMethod = testHandlerMethod()

		request.setAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE, handlerMethod)
		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "/api/travels/{travelId}")
		assertEquals("/api/travels/{travelId}", RequestRouteResolver.resolveRoute(request))

		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "   ")
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, RequestRouteResolver.resolveRoute(request))

		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "/api/safe\r\nforged")
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, RequestRouteResolver.resolveRoute(request))

		val maximumLengthRoute = "/${"a".repeat(255)}"
		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, maximumLengthRoute)
		assertEquals(maximumLengthRoute, RequestRouteResolver.resolveRoute(request))

		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "/${"a".repeat(256)}")
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, RequestRouteResolver.resolveRoute(request))

		request.setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "/api/travels/{travelId}")
		request.setAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE, Any())
		assertEquals(RequestRouteResolver.UNRESOLVED_ROUTE, RequestRouteResolver.resolveRoute(request))

		assertEquals("PATCH", RequestRouteResolver.resolveMethod("patch"))
		assertEquals(RequestRouteResolver.OTHER_METHOD, RequestRouteResolver.resolveMethod("CUSTOM\r\nMETHOD"))
	}

	@Test
	fun `unexpected failure emits safe failure and completion events without throwable`() {
		val request = MockHttpServletRequest("GET", "/api/failure")
		val response = MockHttpServletResponse()
		val failure = IllegalStateException("token=internal-secret&url=https://private.example")

		assertThrows(IllegalStateException::class.java) {
			requestLoggingFilter.doFilter(request, response, FilterChain { _, _ -> throw failure })
		}

		assertEquals(2, logAppender.list.size)
		val failureLog = logAppender.list.single { it.keyValues()["event"] == "UNEXPECTED_REQUEST_FAILURE" }
		val completionLog = logAppender.list.single { it.keyValues()["event"] == "HTTP_REQUEST_COMPLETED" }
		val failureValues = failureLog.keyValues()
		val allLoggedValues = logAppender.list.joinToString { "${it.formattedMessage} ${it.keyValues()}" }

		assertEquals(Level.ERROR, failureLog.level)
		assertEquals(Level.ERROR, completionLog.level)
		assertNull(failureLog.throwableProxy)
		assertNull(completionLog.throwableProxy)
		assertEquals(IllegalStateException::class.java.name, failureValues["errorType"])
		assertTrue((failureValues["errorFingerprint"] as String).matches(Regex("^[0-9a-f]{64}$")))
		assertEquals("500", completionLog.keyValues()["status"].toString())
		assertEquals("INTERNAL_SERVER_ERROR", completionLog.keyValues()["errorCode"])
		assertFalse(allLoggedValues.contains("internal-secret"))
		assertFalse(allLoggedValues.contains("private.example"))
		assertNull(MDC.get(RequestIdGenerator.MDC_KEY))
	}

	@Test
	fun `successful health request is omitted while failed health request is logged`() {
		val successfulRequest = MockHttpServletRequest("GET", "/actuator/health")
		requestLoggingFilter.doFilter(successfulRequest, MockHttpServletResponse(), FilterChain { _, _ -> })
		assertTrue(logAppender.list.isEmpty())

		val failedRequest = MockHttpServletRequest("GET", "/actuator/health/readiness")
		val failedResponse = MockHttpServletResponse()
		requestLoggingFilter.doFilter(
			failedRequest,
			failedResponse,
			FilterChain { _, servletResponse -> (servletResponse as MockHttpServletResponse).status = 503 },
		)

		assertEquals(Level.ERROR, logAppender.list.single().level)
		assertEquals("503", logAppender.list.single().keyValues()["status"].toString())
	}

	private fun assertDecision(
		httpStatus: Int,
		errorCode: ErrorCode?,
		expectedLevel: RequestLogLevel,
		expectedOutcome: LogOutcome,
	) {
		val decision = RequestLogLevelPolicy.resolve(httpStatus, errorCode)

		assertEquals(expectedLevel, decision.level)
		assertEquals(expectedOutcome, decision.outcome)
	}

	private fun createSensitiveRequest(): MockHttpServletRequest =
		MockHttpServletRequest("POST", "/api/travels/$RAW_TRAVEL_ID").apply {
			addHeader(RequestIdGenerator.HEADER_NAME, CLIENT_REQUEST_ID)
			addHeader(HttpHeaders.AUTHORIZATION, "Bearer jwt-secret")
			addHeader(HttpHeaders.COOKIE, "refreshToken=cookie-secret")
			queryString = "code=oauth-secret&state=state-secret"
			setContent("{\"password\":\"password-secret\"}".toByteArray())
			setAttribute(HandlerMapping.BEST_MATCHING_HANDLER_ATTRIBUTE, testHandlerMethod())
			setAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE, "/api/travels/{travelId}")
		}

	private fun testHandlerMethod(): HandlerMethod = HandlerMethod(
		TestHandler(),
		TestHandler::class.java.getDeclaredMethod("handle"),
	)

	private fun ILoggingEvent.keyValues(): Map<String, Any> =
		keyValuePairs.associate { it.key to it.value }

	private class TestHandler {
		fun handle() = Unit
	}

	companion object {
		private const val CLIENT_REQUEST_ID = "client-request-id-sentinel"
		private const val RAW_TRAVEL_ID = "018f1ed0-dead-beef-acde-0242ac120002"
	}
}
