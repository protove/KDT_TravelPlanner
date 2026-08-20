package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.place.port.PlaceSearchPort
import com.ktcloud.travelplanner.place.port.PlaceSearchResult
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import java.math.BigDecimal
import kotlin.test.assertEquals

class PlaceSearchServiceTest {
	private val fakePort = FakePlaceSearchPort()
	private val service = PlaceSearchService(fakePort)

	@Test
	fun `normalizes inputs and maps standard place results`() {
		fakePort.results = listOf(
			PlaceSearchResult(
				placeId = "google-place-id",
				name = "도쿄 타워",
				latitude = BigDecimal("35.658581"),
				longitude = BigDecimal("139.745433"),
				rating = BigDecimal("4.5"),
			),
		)

		val results = service.searchPlaces("  도쿄 타워  ", "jp")

		assertEquals("도쿄 타워", fakePort.query)
		assertEquals("JP", fakePort.countryCode)
		assertEquals("google-place-id", results.single().placeId)
		assertEquals(BigDecimal("4.5"), results.single().rating)
	}

	@Test
	fun `returns empty results and rejects invalid inputs before calling port`() {
		assertEquals(emptyList(), service.searchPlaces("없는 장소", "KR"))

		listOf(
			"" to "KR",
			"   " to "KR",
			"장소" to "K",
			"장소" to "K1",
		).forEach { (query, countryCode) ->
			assertThrows<InvalidPlaceSearchRequestException> {
				service.searchPlaces(query, countryCode)
			}
		}
	}

	@Test
	fun `searches nearby places with valid coordinates and radius`() {
		fakePort.results = listOf(
			PlaceSearchResult(
				placeId = "nearby-place-id",
				name = "남산서울타워",
				latitude = BigDecimal("37.551169"),
				longitude = BigDecimal("126.988227"),
				rating = BigDecimal("4.5"),
			),
		)

		val results = service.searchNearbyPlaces(
			latitude = BigDecimal("37.5665"),
			longitude = BigDecimal("126.9780"),
			radiusMeters = 1500.0,
		)

		assertEquals(BigDecimal("37.5665"), fakePort.latitude)
		assertEquals(BigDecimal("126.9780"), fakePort.longitude)
		assertEquals(1500.0, fakePort.radiusMeters)
		assertEquals("nearby-place-id", results.single().placeId)
		assertEquals("남산서울타워", results.single().name)
		assertEquals(BigDecimal("4.5"), results.single().rating)
	}

	@Test
	fun `rejects invalid nearby latitude`() {
		listOf(
			BigDecimal("-90.0001"),
			BigDecimal("90.0001"),
		).forEach { latitude ->
			assertThrows<InvalidPlaceSearchRequestException> {
				service.searchNearbyPlaces(
					latitude = latitude,
					longitude = BigDecimal("126.9780"),
					radiusMeters = 1500.0,
				)
			}
		}
	}

	@Test
	fun `rejects invalid nearby longitude`() {
		listOf(
			BigDecimal("-180.0001"),
			BigDecimal("180.0001"),
		).forEach { longitude ->
			assertThrows<InvalidPlaceSearchRequestException> {
				service.searchNearbyPlaces(
					latitude = BigDecimal("37.5665"),
					longitude = longitude,
					radiusMeters = 1500.0,
				)
			}
		}
	}

	@Test
	fun `rejects invalid nearby radius`() {
		listOf(
			0.0,
			-1.0,
			50_000.1,
			Double.NaN,
			Double.POSITIVE_INFINITY,
			Double.NEGATIVE_INFINITY,
		).forEach { radiusMeters ->
			assertThrows<InvalidPlaceSearchRequestException> {
				service.searchNearbyPlaces(
					latitude = BigDecimal("37.5665"),
					longitude = BigDecimal("126.9780"),
					radiusMeters = radiusMeters,
				)
			}
		}
	}

	private class FakePlaceSearchPort : PlaceSearchPort {
		var query: String? = null
		var countryCode: String? = null
		var latitude: BigDecimal? = null
		var longitude: BigDecimal? = null
		var radiusMeters: Double? = null
		var results: List<PlaceSearchResult> = emptyList()

		override fun searchPlaces(
			query: String,
			countryCode: String,
		): List<PlaceSearchResult> {
			this.query = query
			this.countryCode = countryCode
			return results
		}

		override fun searchNearbyPlaces(
			latitude: BigDecimal,
			longitude: BigDecimal,
			radiusMeters: Double,
		): List<PlaceSearchResult> {
			this.latitude = latitude
			this.longitude = longitude
			this.radiusMeters = radiusMeters
			return results
		}
	}
}