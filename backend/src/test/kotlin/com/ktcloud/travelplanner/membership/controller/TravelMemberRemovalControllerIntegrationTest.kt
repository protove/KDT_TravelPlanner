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
class TravelMemberRemovalControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner removes accepted member and access is immediately blocked`() {
		val owner = saveUser("remove-owner")
		val memberUser = saveUser("remove-member")
		val travel = saveTravel(owner, "방출 여행")
		val member = saveMember(travel, memberUser, true)

		remove(travel.id, requireNotNull(memberUser.id), owner).andExpect { status { isOk() } }
		entityManager.flush()
		entityManager.clear()
		assertFalse(travelMemberRepository.existsById(member.id))

		get("/api/v1/travels/${travel.id}", memberUser).andExpect { status { isForbidden() } }
		get("/api/v1/travels/${travel.id}/members", memberUser).andExpect { status { isForbidden() } }
	}

	@Test
	fun `non owner owner target pending and other travel member are rejected`() {
		val owner = saveUser("remove-check-owner")
		val acceptedUser = saveUser("remove-check-member")
		val pendingUser = saveUser("remove-check-pending")
		val otherUser = saveUser("remove-check-other")
		val travel = saveTravel(owner, "방출 검증")
		val otherTravel = saveTravel(owner, "다른 방출 여행")
		saveMember(travel, acceptedUser, true)
		saveMember(travel, pendingUser, false)
		saveMember(otherTravel, otherUser, true)

		remove(travel.id, requireNotNull(acceptedUser.id), acceptedUser).andExpect { status { isForbidden() } }
		remove(travel.id, requireNotNull(owner.id), owner).andExpect {
			status { isBadRequest() }
			jsonPath("$.code", equalTo("INVALID_REQUEST"))
		}
		remove(travel.id, requireNotNull(pendingUser.id), owner).andExpect { status { isBadRequest() } }
		remove(travel.id, requireNotNull(otherUser.id), owner).andExpect { status { isNotFound() } }
	}

	private fun remove(travelId: UUID, memberId: UUID, requester: User) =
		mockMvc.delete("/api/v1/travels/$travelId/members/$memberId") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}

	private fun get(path: String, requester: User) = mockMvc.get(path) {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
	}

	private fun bearer(user: User) = "Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String) = userRepository.saveAndFlush(
		User(OAuthProvider.GOOGLE, "member-remove-${UUID.randomUUID()}").also {
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(owner: User, title: String) = travelRepository.saveAndFlush(
		Travel(owner = owner, title = title, startDate = LocalDate.parse("2026-08-01"), endDate = LocalDate.parse("2026-08-02")),
	)

	private fun saveMember(travel: Travel, user: User, isAccepted: Boolean): TravelMember {
		val member = TravelMember(travel = travel, user = user, role = TravelRole.READ_ONLY, invitedAt = Instant.parse("2026-07-01T00:00:00Z"))
		if (isAccepted) member.respond(TravelInvitationAction.ACCEPT, Instant.parse("2026-07-02T00:00:00Z"))
		return travelMemberRepository.saveAndFlush(member)
	}
}
