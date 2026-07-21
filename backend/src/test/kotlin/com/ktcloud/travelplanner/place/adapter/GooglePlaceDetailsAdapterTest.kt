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
import java.net.InetSocketAddress
import java.net.URI
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.assertEquals
import kotlin.test.assertNull

class GooglePlaceDetailsAdapterTest {
	private lateinit var server: HttpServer
	private val handler = AtomicReference<(HttpExchange) -> Unit>()

	@BeforeEach
	fun setUp() {
		server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
			createContext("/v1/places/") { exchange -> handler.get().invoke(exchange) }
			start()
		}
	}

	@AfterEach
	fun tearDown() {
		server.stop(0)
	}

	@Test
	fun `maps location and sends key and location field mask`() {
		handler.set { exchange ->
			assertEquals("/v1/places/place%20id", exchange.requestURI.rawPath)
			assertEquals("test-places-key", exchange.requestHeaders.getFirst("X-Goog-Api-Key"))
			assertEquals("location", exchange.requestHeaders.getFirst("X-Goog-FieldMask"))
			respond(
				exchange,
				200,
				"""{"location":{"latitude":35.658581,"longitude":139.745433}}""",
			)
		}

		val result = requireNotNull(adapter().findLocation("place id"))

		assertEquals("35.658581", result.latitude.toPlainString())
		assertEquals("139.745433", result.longitude.toPlainString())
	}

	@Test
	fun `returns null for a missing Place ID`() {
		handler.set { exchange -> respond(exchange, 404, "{}") }

		assertNull(adapter().findLocation("missing-place"))
	}

	@Test
	fun `rejects malformed and out of range provider locations`() {
		handler.set { exchange -> respond(exchange, 200, "{}") }
		assertThrows<GooglePlacesProviderException> { adapter().findLocation("missing-location") }

		handler.set { exchange ->
			respond(exchange, 200, """{"location":{"latitude":91,"longitude":139.745433}}""")
		}
		assertThrows<GooglePlacesProviderException> { adapter().findLocation("invalid-location") }
	}

	@Test
	fun `maps quota provider timeout and missing key errors`() {
		handler.set { exchange -> respond(exchange, 429, "{}") }
		assertThrows<GooglePlacesQuotaExceededException> { adapter().findLocation("quota") }

		handler.set { exchange -> respond(exchange, 500, "{}") }
		assertThrows<GooglePlacesProviderException> { adapter().findLocation("provider") }

		handler.set { exchange ->
			Thread.sleep(200)
			respond(exchange, 200, """{"location":{"latitude":35,"longitude":139}}""")
		}
		assertThrows<GooglePlacesTimeoutException> {
			adapter(readTimeout = Duration.ofMillis(50)).findLocation("timeout")
		}

		assertThrows<GooglePlacesNotConfiguredException> { adapter(apiKey = "").findLocation("missing-key") }
	}

	private fun adapter(
		apiKey: String = "test-places-key",
		readTimeout: Duration = Duration.ofSeconds(1),
	): GooglePlaceDetailsAdapter = GooglePlaceDetailsAdapter(
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
