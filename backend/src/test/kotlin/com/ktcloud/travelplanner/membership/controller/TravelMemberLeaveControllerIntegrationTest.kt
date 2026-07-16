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
import org.springframework.test.web.servlet.get
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
class TravelMemberLeaveControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `accepted members leave travel and access is immediately blocked`() {
		listOf(TravelRole.READ_ONLY, TravelRole.READ_WRITE).forEach { role ->
			val owner = saveUser("leave-owner-${role.name.lowercase()}")
			val memberUser = saveUser("leave-member-${role.name.lowercase()}")
			val travel = saveTravel(owner, "${role.name} 나가기 여행")
			val member = saveMember(travel, memberUser, role, isAccepted = true)

			leave(travel.id, memberUser).andExpect { status { isOk() } }
			entityManager.flush()
			entityManager.clear()
			assertFalse(travelMemberRepository.existsById(member.id))

			get("/api/v1/travels/${travel.id}", memberUser).andExpect { status { isForbidden() } }
			get("/api/v1/travels/${travel.id}/members", memberUser).andExpect { status { isForbidden() } }
		}
	}

	@Test
	fun `owner pending member and outsider cannot leave travel`() {
		val owner = saveUser("leave-check-owner")
		val pendingUser = saveUser("leave-check-pending")
		val outsider = saveUser("leave-check-outsider")
		val travel = saveTravel(owner, "나가기 검증 여행")
		saveMember(travel, pendingUser, TravelRole.READ_ONLY, isAccepted = false)

		leave(travel.id, owner).andExpect {
			status { isBadRequest() }
			jsonPath("$.code", equalTo("INVALID_REQUEST"))
		}
		leave(travel.id, pendingUser).andExpect {
			status { isBadRequest() }
			jsonPath("$.code", equalTo("INVALID_REQUEST"))
		}
		leave(travel.id, outsider).andExpect {
			status { isNotFound() }
			jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
		}
	}

	@Test
	fun `unauthenticated member cannot leave travel`() {
		val owner = saveUser("leave-auth-owner")
		val travel = saveTravel(owner, "나가기 인증 여행")

		mockMvc.delete("/api/v1/travels/${travel.id}/members/me")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun leave(travelId: UUID, requester: User) =
		mockMvc.delete("/api/v1/travels/$travelId/members/me") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}

	private fun get(path: String, requester: User) = mockMvc.get(path) {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(OAuthProvider.GOOGLE, "member-leave-${UUID.randomUUID()}").also {
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(owner: User, title: String): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = title,
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-02"),
		),
	)

	private fun saveMember(
		travel: Travel,
		user: User,
		role: TravelRole,
		isAccepted: Boolean,
	): TravelMember {
		val member = TravelMember(
			travel = travel,
			user = user,
			role = role,
			invitedAt = Instant.parse("2026-07-01T00:00:00Z"),
		)
		if (isAccepted) {
			member.respond(TravelInvitationAction.ACCEPT, Instant.parse("2026-07-02T00:00:00Z"))
		}
		return travelMemberRepository.saveAndFlush(member)
	}
}
