package com.ktcloud.travelplanner.location.repository

import com.ktcloud.travelplanner.location.model.City
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.Optional

interface CityRepository : JpaRepository<City, Long> {
	@Query(
		"""
		SELECT city
		FROM City city
		WHERE city.country.id = :countryId
		  AND city.isActive = true
		ORDER BY city.displayOrder, city.nameKo, city.id
		""",
	)
	fun findActiveByCountryId(@Param("countryId") countryId: Short): List<City>

	fun findByIdAndIsActiveTrue(cityId: Long): Optional<City>
}
