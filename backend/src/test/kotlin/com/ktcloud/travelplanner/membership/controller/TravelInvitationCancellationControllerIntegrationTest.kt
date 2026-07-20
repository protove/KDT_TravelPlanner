package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.delete
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertFalse

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelInvitationCancellationControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner cancels pending invitation and membership row is deleted`() {
		val owner = saveUser("cancel-owner")
		val invitee = saveUser("cancel-invitee")
		val travel = saveTravel(owner, "취소할 초대")
		val invitation = saveInvitation(travel, invitee)

		cancel(travel.id, invitation.id, owner)
			.andExpect {
				status { isOk() }
			}

		entityManager.flush()
		entityManager.clear()
		assertFalse(travelMemberRepository.existsById(invitation.id))
	}

	@Test
	fun `non owner and mismatched travel cannot cancel invitation`() {
		val owner = saveUser("cancel-access-owner")
		val invitee = saveUser("cancel-access-invitee")
		val travel = saveTravel(owner, "취소 권한 여행")
		val otherTravel = saveTravel(owner, "다른 여행")
		val invitation = saveInvitation(travel, invitee)

		cancel(travel.id, invitation.id, invitee)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
		cancel(otherTravel.id, invitation.id, owner)
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	@Test
	fun `accepted and rejected invitations cannot be cancelled`() {
		val owner = saveUser("cancel-status-owner")
		val invitee = saveUser("cancel-status-invitee")
		val acceptedTravel = saveTravel(owner, "수락된 초대")
		val rejectedTravel = saveTravel(owner, "거절된 초대")
		val accepted = saveInvitation(acceptedTravel, invitee, TravelInvitationAction.ACCEPT)
		val rejected = saveInvitation(rejectedTravel, invitee, TravelInvitationAction.REJECT)

		cancel(acceptedTravel.id, accepted.id, owner)
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
		cancel(rejectedTravel.id, rejected.id, owner)
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	@Test
	fun `unauthenticated user cannot cancel invitation`() {
		val owner = saveUser("cancel-auth-owner")
		val invitee = saveUser("cancel-auth-invitee")
		val travel = saveTravel(owner, "인증 검증 여행")
		val invitation = saveInvitation(travel, invitee)

		mockMvc.delete("/api/v1/travels/${travel.id}/invitations/${invitation.id}")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun cancel(
		travelId: UUID,
		invitationId: UUID,
		requester: User,
	) = mockMvc.delete("/api/v1/travels/$travelId/invitations/$invitationId") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "invitation-cancel-${UUID.randomUUID()}",
		).also {
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(
		owner: User,
		title: String,
	): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = title,
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		),
	)

	private fun saveInvitation(
		travel: Travel,
		invitee: User,
		action: TravelInvitationAction? = null,
	): TravelMember {
		val invitation = TravelMember(
			travel = travel,
			user = invitee,
			role = TravelRole.READ_WRITE,
			invitedAt = Instant.parse("2026-07-01T00:00:00Z"),
		)
		action?.let {
			invitation.respond(it, Instant.parse("2026-07-02T00:00:00Z"))
		}
		return travelMemberRepository.saveAndFlush(invitation)
	}
}
