package com.ktcloud.travelplanner.location.model

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.Id
import jakarta.persistence.Table
import org.hibernate.annotations.JdbcTypeCode
import org.hibernate.type.SqlTypes

@Entity
@Table(name = "country_table")
class Country(
	@Id
	val id: Short,

	@Column(nullable = false, unique = true, length = 2, columnDefinition = "CHAR(2)")
	@JdbcTypeCode(SqlTypes.CHAR)
	val code: String,

	@Column(name = "name_ko", nullable = false, length = 50)
	val nameKo: String,

	@Column(name = "name_en", nullable = false, length = 100)
	val nameEn: String,

	@Column(name = "display_order", nullable = false)
	val displayOrder: Short = 0,

	@Column(name = "is_active", nullable = false)
	val isActive: Boolean = true,
)
