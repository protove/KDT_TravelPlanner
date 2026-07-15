package com.ktcloud.travelplanner.user.model

import com.ktcloud.travelplanner.global.model.BaseTimeEntity
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.Table
import org.hibernate.annotations.SQLRestriction
import java.time.Instant
import java.util.UUID

@Entity
@Table(name = "user_table")
@SQLRestriction("deleted_at IS NULL")
class User(
	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 20)
	val provider: OAuthProvider,

	@Column(name = "provider_user_id", nullable = false, length = 255)
	val providerUserId: String,

	email: String? = null,
	name: String? = null,
) : BaseTimeEntity() {
	@Id
	@GeneratedValue(strategy = GenerationType.UUID)
	var id: UUID? = null
		protected set

	@Column(length = 255)
	var email: String? = email
		protected set

	@Column(length = 100)
	var name: String? = name
		protected set

	@Column(length = 30)
	var nickname: String? = null
		protected set

	@Column(name = "profile_image_url", columnDefinition = "TEXT")
	var profileImageUrl: String? = null
		protected set

	@Enumerated(EnumType.STRING)
	@Column(length = 20)
	var gender: Gender? = null
		protected set

	@Column(name = "birth_year")
	var birthYear: Short? = null
		protected set

	@Column(name = "profile_completed", nullable = false)
	var isProfileCompleted: Boolean = false
		protected set

	@Column(name = "deleted_at")
	var deletedAt: Instant? = null
		protected set

	val isDeleted: Boolean
		get() = deletedAt != null

	init {
		require(providerUserId.isNotBlank()) { "providerUserId must not be blank." }
		require(providerUserId.length <= PROVIDER_USER_ID_MAX_LENGTH) {
			"providerUserId must not exceed $PROVIDER_USER_ID_MAX_LENGTH characters."
		}
	}

	fun updateOAuthProfile(
		email: String?,
		name: String?,
		profileImageUrl: String?,
	) {
		require(email == null || email.length <= EMAIL_MAX_LENGTH) {
			"email must not exceed $EMAIL_MAX_LENGTH characters."
		}
		require(name == null || name.length <= NAME_MAX_LENGTH) {
			"name must not exceed $NAME_MAX_LENGTH characters."
		}

		this.email = email
		this.name = name
		this.profileImageUrl = profileImageUrl
	}

	fun completeProfile(
		nickname: String,
		gender: Gender?,
		birthYear: Int?,
	) {
		require(nickname.isNotBlank()) { "nickname must not be blank." }
		require(nickname.length <= NICKNAME_MAX_LENGTH) {
			"nickname must not exceed $NICKNAME_MAX_LENGTH characters."
		}
		require(birthYear == null || birthYear in MIN_BIRTH_YEAR..MAX_BIRTH_YEAR) {
			"birthYear must be between $MIN_BIRTH_YEAR and $MAX_BIRTH_YEAR."
		}

		this.nickname = nickname
		this.gender = gender
		this.birthYear = birthYear?.toShort()
		isProfileCompleted = true
	}

	fun softDelete(deletedAt: Instant) {
		require(this.deletedAt == null) { "User is already deleted." }
		this.deletedAt = deletedAt
	}

	companion object {
		private const val PROVIDER_USER_ID_MAX_LENGTH = 255
		private const val EMAIL_MAX_LENGTH = 255
		private const val NAME_MAX_LENGTH = 100
		private const val NICKNAME_MAX_LENGTH = 30
		private const val MIN_BIRTH_YEAR = 1900
		private const val MAX_BIRTH_YEAR = 2100
	}
}
