package com.ktcloud.travelplanner.route.adapter

import com.ktcloud.travelplanner.route.config.GoogleRoutesProperties
import com.ktcloud.travelplanner.route.exception.GoogleRoutesNotConfiguredException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesProviderException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesQuotaExceededException
import com.ktcloud.travelplanner.route.exception.GoogleRoutesTimeoutException
import com.ktcloud.travelplanner.route.model.TransportationType
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.MediaType
import org.springframework.web.client.RestClient
import java.net.InetSocketAddress
import java.net.URI
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class GoogleRoutesAdapterTest {
	private lateinit var server: HttpServer
	private val handler = AtomicReference<(HttpExchange) -> Unit>()

	@BeforeEach
	fun setUp() {
		server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
			createContext("/directions/v2:computeRoutes") { exchange -> handler.get().invoke(exchange) }
			start()
		}
	}

	@AfterEach
	fun tearDown() {
		server.stop(0)
	}

	@Test
	fun `sends ordered waypoints and maps polyline legs duration and warnings`() {
		handler.set { exchange ->
			val body = exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8)
			assertEquals("POST", exchange.requestMethod)
			assertEquals("routes-key", exchange.requestHeaders.getFirst("X-Goog-Api-Key"))
			assertTrue(exchange.requestHeaders.getFirst("X-Goog-FieldMask").contains("routes.warnings"))
			assertTrue(body.contains("\"origin\":{\"placeId\":\"place-1\"}"))
			assertTrue(body.contains("\"intermediates\":[{\"placeId\":\"place-2\"}]"))
			assertTrue(body.contains("\"destination\":{\"placeId\":\"place-3\"}"))
			assertTrue(body.contains("\"travelMode\":\"WALK\""))
			respond(
				exchange,
				200,
				"""{"routes":[{"distanceMeters":1200,"duration":"900s","polyline":{"encodedPolyline":"polyline"},"legs":[{"distanceMeters":500,"duration":"300s"},{"distanceMeters":700,"duration":"600s"}],"warnings":["보행 경로 주의"]}]}""",
			)
		}

		val result = adapter().calculateRoute(listOf("place-1", "place-2", "place-3"), TransportationType.WALK)

		assertEquals("polyline", result.encodedPolyline)
		assertEquals(1200, result.totalDistanceMeters)
		assertEquals(900, result.totalDurationSeconds)
		assertEquals(listOf(500L, 700L), result.legs.map { it.distanceMeters })
		assertEquals(listOf("보행 경로 주의"), result.warnings)
	}

	@Test
	fun `rejects malformed route and maps provider errors`() {
		handler.set { exchange -> respond(exchange, 200, """{"routes":[]}""") }
		val noRoute = adapter().calculateRoute(listOf("a", "b"), TransportationType.DRIVE)
		assertEquals(null, noRoute.encodedPolyline)
		assertTrue(noRoute.encodedPolylines.isEmpty())
		assertEquals(0, noRoute.totalDistanceMeters)
		assertEquals(0, noRoute.totalDurationSeconds)
		assertTrue(noRoute.legs.isEmpty())

		handler.set { exchange -> respond(exchange, 429, "{}") }
		assertThrows<GoogleRoutesQuotaExceededException> {
			adapter().calculateRoute(listOf("a", "b"), TransportationType.BICYCLE)
		}

		handler.set { exchange -> respond(exchange, 500, "{}") }
		assertThrows<GoogleRoutesProviderException> {
			adapter().calculateRoute(listOf("a", "b"), TransportationType.DRIVE)
		}
	}

	@Test
	fun `maps timeout and missing key errors`() {
		handler.set { exchange ->
			Thread.sleep(200)
			respond(exchange, 200, "{}")
		}
		assertThrows<GoogleRoutesTimeoutException> {
			adapter(readTimeout = Duration.ofMillis(50))
				.calculateRoute(listOf("a", "b"), TransportationType.DRIVE)
		}
		assertThrows<GoogleRoutesNotConfiguredException> {
			adapter(apiKey = "").calculateRoute(listOf("a", "b"), TransportationType.DRIVE)
		}
	}

	private fun adapter(
		apiKey: String = "routes-key",
		readTimeout: Duration = Duration.ofSeconds(1),
	) = GoogleRoutesAdapter(
		RestClient.builder(),
		GoogleRoutesProperties(
			apiKey = apiKey,
			baseUrl = URI.create("http://127.0.0.1:${server.address.port}"),
			connectTimeout = Duration.ofSeconds(1),
			readTimeout = readTimeout,
		),
	)

	private fun respond(exchange: HttpExchange, status: Int, body: String) {
		val bytes = body.toByteArray(StandardCharsets.UTF_8)
		exchange.responseHeaders.set("Content-Type", MediaType.APPLICATION_JSON_VALUE)
		exchange.sendResponseHeaders(status, bytes.size.toLong())
		exchange.responseBody.use { it.write(bytes) }
	}
}
