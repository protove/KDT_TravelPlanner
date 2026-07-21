package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.place.port.PlaceLocationCache
import com.ktcloud.travelplanner.place.port.PlaceLocationPort
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.math.BigDecimal
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PlaceLocationServiceTest {
	private val placeLocationCache = mock(PlaceLocationCache::class.java)
	private val placeLocationPort = mock(PlaceLocationPort::class.java)
	private val service = PlaceLocationService(placeLocationCache, placeLocationPort)
	private val location = PlaceLocation(BigDecimal("35.658581"), BigDecimal("139.745433"))

	@Test
	fun `returns cached location without calling provider`() {
		`when`(placeLocationCache.findLocation(PLACE_ID)).thenReturn(location)

		assertEquals(location, service.getLocation(PLACE_ID))
		verifyNoInteractions(placeLocationPort)
		verify(placeLocationCache, never()).saveLocation(PLACE_ID, location)
	}

	@Test
	fun `resolves and caches location on cache miss`() {
		`when`(placeLocationCache.findLocation(PLACE_ID)).thenReturn(null)
		`when`(placeLocationPort.findLocation(PLACE_ID)).thenReturn(location)

		assertEquals(location, service.getLocation(PLACE_ID))
		verify(placeLocationCache).saveLocation(PLACE_ID, location)
	}

	@Test
	fun `does not cache an unresolved place`() {
		`when`(placeLocationCache.findLocation(PLACE_ID)).thenReturn(null)
		`when`(placeLocationPort.findLocation(PLACE_ID)).thenReturn(null)

		assertNull(service.getLocation(PLACE_ID))
		verify(placeLocationCache, never()).saveLocation(PLACE_ID, location)
	}

	@Test
	fun `rejects blank Place ID before cache or provider access`() {
		assertThrows<IllegalArgumentException> { service.getLocation(" ") }
		verifyNoInteractions(placeLocationCache, placeLocationPort)
	}

	companion object {
		private const val PLACE_ID = "google-place-id"
	}
}
