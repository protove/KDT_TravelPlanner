package com.ktcloud.travelplanner.location.dto

import com.ktcloud.travelplanner.location.model.City
import java.math.BigDecimal

data class CityResponse(
	val cityId: Long,
	val countryId: Short,
	val nameKo: String,
	val nameEn: String,
	val googlePlaceId: String?,
	val latitude: BigDecimal?,
	val longitude: BigDecimal?,
) {
	companion object {
		fun from(city: City): CityResponse = CityResponse(
			cityId = city.id,
			countryId = city.country.id,
			nameKo = city.nameKo,
			nameEn = city.nameEn,
			googlePlaceId = city.googlePlaceId,
			latitude = city.latitude,
			longitude = city.longitude,
		)
	}
}
