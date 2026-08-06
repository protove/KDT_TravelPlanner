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

		listOf("" to "KR", "   " to "KR", "장소" to "K", "장소" to "K1")
			.forEach { (query, countryCode) ->
				assertThrows<InvalidPlaceSearchRequestException> {
					service.searchPlaces(query, countryCode)
				}
			}
	}

	private class FakePlaceSearchPort : PlaceSearchPort {
		var query: String? = null
		var countryCode: String? = null
		var results: List<PlaceSearchResult> = emptyList()

		override fun searchPlaces(query: String, countryCode: String): List<PlaceSearchResult> {
			this.query = query
			this.countryCode = countryCode
			return results
		}
	}
}
