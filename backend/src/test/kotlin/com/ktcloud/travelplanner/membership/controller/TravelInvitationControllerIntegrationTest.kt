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
import org.springframework.test.web.servlet.post
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
class TravelInvitationControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner creates pending invitation persisted with requested role`() {
		val owner = saveUser("owner")
		val invitee = saveUser("invitee")
		val travel = saveTravel(owner)

		mockMvc.post("/api/v1/travels/${travel.id}/invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
			contentType = MediaType.APPLICATION_JSON
			content = """{"nickname":"invitee","role":"READ_WRITE"}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.invitationId", notNullValue())
			}

		entityManager.flush()
		entityManager.clear()
		val member = travelMemberRepository.findAll().single()
		assertEquals(travel.id, member.travel.id)
		assertEquals(invitee.id, member.user.id)
		assertEquals(TravelRole.READ_WRITE, member.role)
		assertEquals(InvitationStatus.PENDING, member.status)
		assertNotNull(member.invitedAt)
	}

	@Test
	fun `self missing target and duplicate invitations are rejected`() {
		val owner = saveUser("owner-errors")
		val invitee = saveUser("invitee-errors")
		val travel = saveTravel(owner)

		postInvitation(travel, owner, "owner-errors")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
		postInvitation(travel, owner, "missing-user")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}

		travelMemberRepository.saveAndFlush(
			TravelMember(travel = travel, user = invitee, role = TravelRole.READ_ONLY, invitedAt = Instant.now()),
		)
		postInvitation(travel, owner, "invitee-errors")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	@Test
	fun `non owner and unauthenticated users cannot create invitation`() {
		val owner = saveUser("owner-access")
		val invitee = saveUser("invitee-access")
		val travel = saveTravel(owner)

		postInvitation(travel, invitee, "owner-access")
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}

		mockMvc.post("/api/v1/travels/${travel.id}/invitations") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"nickname":"invitee-access","role":"READ_ONLY"}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun postInvitation(
		travel: Travel,
		requester: User,
		nickname: String,
	) = mockMvc.post("/api/v1/travels/${travel.id}/invitations") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = """{"nickname":"$nickname","role":"READ_ONLY"}"""
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "invitation-${UUID.randomUUID()}",
		).also {
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "초대 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		),
	)
}
