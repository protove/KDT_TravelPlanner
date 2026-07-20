package com.ktcloud.travelplanner.membership.model

import com.ktcloud.travelplanner.travel.model.Travel
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
import java.time.Instant
import java.util.UUID

@Entity
@Table(name = "planner_members")
class TravelMember(
	@Id
	val id: UUID = UUID.randomUUID(),

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "planner_id", nullable = false)
	val travel: Travel,

	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "user_id", nullable = false)
	val user: User,

	role: TravelRole,

	@Column(name = "invited_at", nullable = false, updatable = false)
	val invitedAt: Instant,
) {
	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 20)
	var role: TravelRole = role
		protected set

	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 20)
	var status: InvitationStatus = InvitationStatus.PENDING
		protected set

	@Column(name = "responded_at")
	var respondedAt: Instant? = null
		protected set

	fun respond(
		action: TravelInvitationAction,
		respondedAt: Instant,
	) {
		check(status == InvitationStatus.PENDING) { "Only pending invitations can be answered." }
		status = when (action) {
			TravelInvitationAction.ACCEPT -> InvitationStatus.ACCEPTED
			TravelInvitationAction.REJECT -> InvitationStatus.REJECTED
		}
		this.respondedAt = respondedAt
	}

	fun updateRole(role: TravelRole) {
		check(status == InvitationStatus.ACCEPTED) { "Only accepted member roles can be changed." }
		this.role = role
	}
}
