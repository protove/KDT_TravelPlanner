package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.InvitationStatus
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
import org.hamcrest.Matchers.notNullValue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelInvitationResponseControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `invitee can accept or reject pending invitations and response time is persisted`() {
		val owner = saveUser("response-owner")
		val invitee = saveUser("response-invitee")
		val acceptedInvitation = saveInvitation(saveTravel(owner, "수락할 여행"), invitee)
		val rejectedInvitation = saveInvitation(saveTravel(owner, "거절할 여행"), invitee)

		respond(acceptedInvitation.id, invitee, "ACCEPT")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.invitationId", equalTo(acceptedInvitation.id.toString()))
				jsonPath("$.data.status", equalTo("ACCEPTED"))
				jsonPath("$.data.respondedAt", notNullValue())
			}
		respond(rejectedInvitation.id, invitee, "REJECT")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.status", equalTo("REJECTED"))
				jsonPath("$.data.respondedAt", notNullValue())
			}

		entityManager.flush()
		entityManager.clear()
		val accepted = travelMemberRepository.findById(acceptedInvitation.id).orElseThrow()
		val rejected = travelMemberRepository.findById(rejectedInvitation.id).orElseThrow()
		assertEquals(InvitationStatus.ACCEPTED, accepted.status)
		assertNotNull(accepted.respondedAt)
		assertEquals(InvitationStatus.REJECTED, rejected.status)
		assertNotNull(rejected.respondedAt)
	}

	@Test
	fun `other user is forbidden and already answered invitation returns conflict`() {
		val owner = saveUser("response-access-owner")
		val invitee = saveUser("response-access-invitee")
		val otherUser = saveUser("response-access-other")
		val invitation = saveInvitation(saveTravel(owner, "권한 검증 여행"), invitee)

		respond(invitation.id, otherUser, "ACCEPT")
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
		respond(invitation.id, invitee, "ACCEPT")
			.andExpect {
				status { isOk() }
			}
		respond(invitation.id, invitee, "REJECT")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	@Test
	fun `invalid action and unauthenticated request are rejected`() {
		val owner = saveUser("response-validation-owner")
		val invitee = saveUser("response-validation-invitee")
		val invitation = saveInvitation(saveTravel(owner, "입력 검증 여행"), invitee)

		respond(invitation.id, invitee, "HOLD")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("MALFORMED_JSON"))
			}

		mockMvc.patch("/api/v1/travel-invitations/${invitation.id}") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"action":"ACCEPT"}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun respond(
		invitationId: UUID,
		user: User,
		action: String,
	) = mockMvc.patch("/api/v1/travel-invitations/$invitationId") {
		header(HttpHeaders.AUTHORIZATION, bearer(user))
		contentType = MediaType.APPLICATION_JSON
		content = """{"action":"$action"}"""
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "invitation-response-${UUID.randomUUID()}",
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
	): TravelMember = travelMemberRepository.saveAndFlush(
		TravelMember(
			travel = travel,
			user = invitee,
			role = TravelRole.READ_WRITE,
			invitedAt = Instant.parse("2026-07-01T00:00:00Z"),
		),
	)
}
