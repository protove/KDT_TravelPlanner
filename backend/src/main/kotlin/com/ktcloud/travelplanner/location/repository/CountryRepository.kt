package com.ktcloud.travelplanner.location.repository

import com.ktcloud.travelplanner.location.model.Country
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import java.util.Optional

interface CountryRepository : JpaRepository<Country, Short> {
	@Query(
		"""
		SELECT country
		FROM Country country
		WHERE country.isActive = true
		ORDER BY country.displayOrder, country.nameKo, country.id
		""",
	)
	fun findActive(): List<Country>

	fun existsByIdAndIsActiveTrue(countryId: Short): Boolean

	fun findByIdAndIsActiveTrue(countryId: Short): Optional<Country>
}
