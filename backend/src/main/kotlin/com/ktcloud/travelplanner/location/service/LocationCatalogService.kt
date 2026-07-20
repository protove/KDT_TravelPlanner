package com.ktcloud.travelplanner.location.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.location.dto.CityResponse
import com.ktcloud.travelplanner.location.dto.CountryResponse
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class LocationCatalogService(
	private val countryRepository: CountryRepository,
	private val cityRepository: CityRepository,
) {
	@Transactional(readOnly = true)
	fun getCountries(): List<CountryResponse> =
		countryRepository.findActive().map(CountryResponse::from)

	@Transactional(readOnly = true)
	fun getCities(countryId: Short): List<CityResponse> {
		if (!countryRepository.existsByIdAndIsActiveTrue(countryId)) {
			throw CountryNotFoundException()
		}
		return cityRepository.findActiveByCountryId(countryId).map(CityResponse::from)
	}
}

class CountryNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)
