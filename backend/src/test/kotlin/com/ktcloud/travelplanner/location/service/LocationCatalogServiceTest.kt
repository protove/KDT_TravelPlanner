package com.ktcloud.travelplanner.location.service

import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.model.Country
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.math.BigDecimal
import kotlin.test.assertEquals

class LocationCatalogServiceTest {
	private val countryRepository = mock(CountryRepository::class.java)
	private val cityRepository = mock(CityRepository::class.java)
	private val service = LocationCatalogService(countryRepository, cityRepository)

	@Test
	fun `maps active countries in repository display order`() {
		`when`(countryRepository.findActive()).thenReturn(
			listOf(
				Country(2, "KR", "대한민국", "South Korea", 0, true),
				Country(1, "JP", "일본", "Japan", 1, true),
			),
		)

		val countries = service.getCountries()

		assertEquals(listOf(2.toShort(), 1.toShort()), countries.map { it.countryId })
		assertEquals(listOf("KR", "JP"), countries.map { it.code })
		verify(countryRepository).findActive()
	}

	@Test
	fun `maps only cities belonging to requested active country`() {
		val country = Country(1, "JP", "일본", "Japan")
		val city = City(
			id = 10,
			country = country,
			nameKo = "도쿄",
			nameEn = "Tokyo",
			googlePlaceId = "tokyo-place",
			latitude = BigDecimal("35.676200"),
			longitude = BigDecimal("139.650300"),
		)
		`when`(countryRepository.existsByIdAndIsActiveTrue(1)).thenReturn(true)
		`when`(cityRepository.findActiveByCountryId(1)).thenReturn(listOf(city))

		val cities = service.getCities(1)

		assertEquals(1, cities.size)
		assertEquals(10, cities.single().cityId)
		assertEquals(1, cities.single().countryId)
		assertEquals("tokyo-place", cities.single().googlePlaceId)
		verify(cityRepository).findActiveByCountryId(1)
	}

	@Test
	fun `rejects absent or inactive country before city lookup`() {
		`when`(countryRepository.existsByIdAndIsActiveTrue(99)).thenReturn(false)

		assertThrows<CountryNotFoundException> {
			service.getCities(99)
		}

		verifyNoInteractions(cityRepository)
	}
}
