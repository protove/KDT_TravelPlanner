package com.ktcloud.travelplanner.location.dto

import com.ktcloud.travelplanner.location.model.Country

data class CountryResponse(
	val countryId: Short,
	val code: String,
	val nameKo: String,
	val nameEn: String,
) {
	companion object {
		fun from(country: Country): CountryResponse = CountryResponse(
			countryId = country.id,
			code = country.code,
			nameKo = country.nameKo,
			nameEn = country.nameEn,
		)
	}
}
