package com.ktcloud.travelplanner.location.model

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import java.math.BigDecimal

@Entity
@Table(name = "city_table")
class City(
	@Id
	val id: Long,

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "country_id", nullable = false)
	val country: Country,

	@Column(name = "name_ko", nullable = false, length = 100)
	val nameKo: String,

	@Column(name = "name_en", nullable = false, length = 100)
	val nameEn: String,

	@Column(name = "google_place_id", length = 255)
	val googlePlaceId: String? = null,

	@Column(precision = 9, scale = 6)
	val latitude: BigDecimal? = null,

	@Column(precision = 10, scale = 6)
	val longitude: BigDecimal? = null,

	@Column(name = "display_order", nullable = false)
	val displayOrder: Short = 0,

	@Column(name = "is_active", nullable = false)
	val isActive: Boolean = true,
)
