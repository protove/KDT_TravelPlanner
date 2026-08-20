package com.ktcloud.travelplanner.place.adapter

import com.ktcloud.travelplanner.place.config.GooglePlacesProperties
import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.http.MediaType
import org.springframework.web.client.RestClient
import java.math.BigDecimal
import java.net.InetSocketAddress
import java.net.URI
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class GooglePlacesAdapterTest {
	private lateinit var server: HttpServer
	private val handler = AtomicReference<(HttpExchange) -> Unit>()

	@BeforeEach
	fun setUp() {
		server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
			createContext("/v1/places:searchText") { exchange -> handler.get().invoke(exchange) }
			createContext("/v1/places:searchNearby") { exchange -> handler.get().invoke(exchange) }
			start()
		}
	}

	@AfterEach
	fun tearDown() {
		server.stop(0)
	}

	@Test
	fun `maps Google response and sends key field mask and normalized request`() {
		val requestBody = AtomicReference<String>()
		handler.set { exchange ->
			assertEquals("test-places-key", exchange.requestHeaders.getFirst("X-Goog-Api-Key"))
			assertEquals(
				"places.id,places.displayName.text,places.location,places.rating",
				exchange.requestHeaders.getFirst("X-Goog-FieldMask"),
			)
			requestBody.set(exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8))
			respond(
				exchange,
				200,
				"""{"places":[{"id":"place-1","displayName":{"text":"도쿄 타워"},"location":{"latitude":35.658581,"longitude":139.745433},"rating":4.5}]}""",
			)
		}

		val result = adapter().searchPlaces("도쿄 타워", "JP").single()

		assertEquals("place-1", result.placeId)
		assertEquals("도쿄 타워", result.name)
		assertEquals("35.658581", result.latitude.toPlainString())
		assertTrue(requireNotNull(requestBody.get()).contains("\"regionCode\":\"JP\""))
	}

	@Test
	fun `maps nearby Google response and sends location restriction request`() {
		val requestBody = AtomicReference<String>()
		handler.set { exchange ->
			assertEquals("test-places-key", exchange.requestHeaders.getFirst("X-Goog-Api-Key"))
			assertEquals(
				"places.id,places.displayName.text,places.location,places.rating",
				exchange.requestHeaders.getFirst("X-Goog-FieldMask"),
			)
			requestBody.set(exchange.requestBody.readAllBytes().toString(StandardCharsets.UTF_8))
			respond(
				exchange,
				200,
				"""{"places":[{"id":"nearby-1","displayName":{"text":"우에노 공원"},"location":{"latitude":35.7148,"longitude":139.7735},"rating":4.4}]}""",
			)
		}

		val result = adapter().searchNearbyPlaces(
			latitude = BigDecimal("35.681236"),
			longitude = BigDecimal("139.767125"),
			radiusMeters = 1500.0,
		).single()

		assertEquals("nearby-1", result.placeId)
		assertEquals("우에노 공원", result.name)
		assertEquals("35.7148", result.latitude.toPlainString())
		assertEquals("139.7735", result.longitude.toPlainString())
		assertEquals("4.4", result.rating?.toPlainString())

		val body = requireNotNull(requestBody.get())
		assertTrue(body.contains("\"locationRestriction\""))
		assertTrue(body.contains("\"latitude\":35.681236"))
		assertTrue(body.contains("\"longitude\":139.767125"))
		assertTrue(body.contains("\"radius\":1500.0") || body.contains("\"radius\":1500"))
	}

	@Test
	fun `returns empty response and rejects malformed provider data`() {
		handler.set { exchange -> respond(exchange, 200, "{}") }
		assertEquals(emptyList(), adapter().searchPlaces("없는 장소", "KR"))

		handler.set { exchange -> respond(exchange, 200, """{"places":[{"id":"missing-fields"}]}""") }
		assertThrows<GooglePlacesProviderException> { adapter().searchPlaces("잘못된 응답", "KR") }
	}

	@Test
	fun `maps quota provider timeout and missing key errors`() {
		handler.set { exchange -> respond(exchange, 429, """{"error":"quota"}""") }
		assertThrows<GooglePlacesQuotaExceededException> { adapter().searchPlaces("quota", "KR") }

		handler.set { exchange -> respond(exchange, 500, """{"error":"provider"}""") }
		assertThrows<GooglePlacesProviderException> { adapter().searchPlaces("provider", "KR") }

		handler.set { exchange ->
			Thread.sleep(200)
			respond(exchange, 200, "{}")
		}
		assertThrows<GooglePlacesTimeoutException> { adapter(readTimeout = Duration.ofMillis(50)).searchPlaces("timeout", "KR") }

		assertThrows<GooglePlacesNotConfiguredException> { adapter(apiKey = "").searchPlaces("missing", "KR") }
	}

	private fun adapter(
		apiKey: String = "test-places-key",
		readTimeout: Duration = Duration.ofSeconds(1),
	): GooglePlacesAdapter = GooglePlacesAdapter(
		RestClient.builder(),
		GooglePlacesProperties(
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
