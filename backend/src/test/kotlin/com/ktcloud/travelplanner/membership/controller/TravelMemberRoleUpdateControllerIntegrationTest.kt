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
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelMemberRoleUpdateControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner changes accepted member role and result is persisted`() {
		val owner = saveUser("role-owner")
		val memberUser = saveUser("role-member")
		val travel = saveTravel(owner, "권한 변경 여행")
		val member = saveMember(travel, memberUser, isAccepted = true)

		updateRole(travel.id, requireNotNull(memberUser.id), owner, "READ_WRITE")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.userId", equalTo(memberUser.id.toString()))
				jsonPath("$.data.role", equalTo("READ_WRITE"))
				jsonPath("$.data.isOwner", equalTo(false))
			}

		entityManager.flush()
		entityManager.clear()
		assertEquals(TravelRole.READ_WRITE, travelMemberRepository.findById(member.id).orElseThrow().role)
	}

	@Test
	fun `non owner cannot change accepted member role`() {
		val owner = saveUser("role-access-owner")
		val memberUser = saveUser("role-access-member")
		val travel = saveTravel(owner, "권한 검증 여행")
		saveMember(travel, memberUser, isAccepted = true)

		updateRole(travel.id, requireNotNull(memberUser.id), memberUser, "READ_ONLY")
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `pending owner and member from other travel are invalid targets`() {
		val owner = saveUser("role-target-owner")
		val pendingUser = saveUser("role-target-pending")
		val otherUser = saveUser("role-target-other")
		val travel = saveTravel(owner, "대상 검증 여행")
		val otherTravel = saveTravel(owner, "다른 권한 여행")
		saveMember(travel, pendingUser, isAccepted = false)
		saveMember(otherTravel, otherUser, isAccepted = true)

		updateRole(travel.id, requireNotNull(pendingUser.id), owner, "READ_WRITE")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
		updateRole(travel.id, requireNotNull(owner.id), owner, "READ_ONLY")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
		updateRole(travel.id, requireNotNull(otherUser.id), owner, "READ_ONLY")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	@Test
	fun `owner role value and unauthenticated request are rejected`() {
		val owner = saveUser("role-input-owner")
		val memberUser = saveUser("role-input-member")
		val travel = saveTravel(owner, "입력 검증 여행")
		saveMember(travel, memberUser, isAccepted = true)

		updateRole(travel.id, requireNotNull(memberUser.id), owner, "OWNER")
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("MALFORMED_JSON"))
			}
		mockMvc.patch("/api/v1/travels/${travel.id}/members/${memberUser.id}") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"role":"READ_ONLY"}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun updateRole(
		travelId: UUID,
		memberId: UUID,
		requester: User,
		role: String,
	) = mockMvc.patch("/api/v1/travels/$travelId/members/$memberId") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = """{"role":"$role"}"""
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(OAuthProvider.GOOGLE, "member-role-${UUID.randomUUID()}").also {
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
		isAccepted: Boolean,
	): TravelMember {
		val member = TravelMember(
			travel = travel,
			user = user,
			role = TravelRole.READ_ONLY,
			invitedAt = Instant.parse("2026-07-01T00:00:00Z"),
		)
		if (isAccepted) {
			member.respond(TravelInvitationAction.ACCEPT, Instant.parse("2026-07-02T00:00:00Z"))
		}
		return travelMemberRepository.saveAndFlush(member)
	}
}
