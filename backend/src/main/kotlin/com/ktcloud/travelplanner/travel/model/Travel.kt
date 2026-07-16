package com.ktcloud.travelplanner.travel.model

import com.ktcloud.travelplanner.global.model.BaseTimeEntity
import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.model.Country
import com.ktcloud.travelplanner.user.model.User
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import jakarta.persistence.Version
import org.hibernate.annotations.SQLRestriction
import java.time.Instant
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.UUID

@Entity
@Table(name = "planners_table")
@SQLRestriction("deleted_at IS NULL")
class Travel(
	@Id
	val id: UUID = UUID.randomUUID(),

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "owner_id", nullable = false)
	val owner: User,

	title: String,
	startDate: LocalDate,
	endDate: LocalDate,
) : BaseTimeEntity() {
	@Column(nullable = false, length = 100)
	var title: String = title
		protected set

	@Column(name = "start_date", nullable = false)
	var startDate: LocalDate = startDate
		protected set

	@Column(name = "end_date", nullable = false)
	var endDate: LocalDate = endDate
		protected set

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "country_id")
	var country: Country? = null
		protected set

	@ManyToOne(fetch = FetchType.LAZY)
	@JoinColumn(name = "city_id")
	var city: City? = null
		protected set

	@Enumerated(EnumType.STRING)
	@Column(name = "companion_type", length = 20)
	var companionType: CompanionType? = null
		protected set

	@Column(name = "companion_count")
	var participantCount: Short? = null
		protected set

	@Column(columnDefinition = "TEXT")
	var comment: String? = null
		protected set

	@Version
	@Column(nullable = false)
	var version: Long = 0
		protected set

	@Column(name = "deleted_at")
	var deletedAt: Instant? = null
		protected set

	val isDeleted: Boolean
		get() = deletedAt != null

	val travelDays: Int
		get() = Math.toIntExact(ChronoUnit.DAYS.between(startDate, endDate) + 1)

	init {
		require(title.isNotBlank()) { "title must not be blank." }
		require(title.length <= TITLE_MAX_LENGTH) { "title must not exceed $TITLE_MAX_LENGTH characters." }
		require(!endDate.isBefore(startDate)) { "endDate must not be before startDate." }
	}

	fun softDelete(deletedAt: Instant) {
		require(this.deletedAt == null) { "Travel is already deleted." }
		this.deletedAt = deletedAt
	}

	fun updateBasicInfo(
		title: String,
		startDate: LocalDate,
		endDate: LocalDate,
		country: Country?,
		city: City?,
		companionType: CompanionType?,
		participantCount: Short?,
		comment: String?,
	) {
		require(title.isNotBlank()) { "title must not be blank." }
		require(title.length <= TITLE_MAX_LENGTH) { "title must not exceed $TITLE_MAX_LENGTH characters." }
		require(!endDate.isBefore(startDate)) { "endDate must not be before startDate." }
		require(participantCount == null || participantCount > 0) { "participantCount must be positive." }
		require(city == null || country != null && city.country.id == country.id) {
			"city must belong to country."
		}

		this.title = title
		this.startDate = startDate
		this.endDate = endDate
		this.country = country
		this.city = city
		this.companionType = companionType
		this.participantCount = participantCount
		this.comment = comment
	}

	companion object {
		private const val TITLE_MAX_LENGTH = 100
	}
}
