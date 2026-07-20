package com.ktcloud.travelplanner.membership.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
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
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.sql.Timestamp
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class ReceivedTravelInvitationControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
	@Autowired private val jdbcTemplate: JdbcTemplate,
) {
	@Test
	fun `received invitations are isolated by user and returned newest first with pagination`() {
		val owner = saveUser("list-owner")
		val invitee = saveUser("list-invitee")
		val otherInvitee = saveUser("list-other")
		val oldestTravel = saveTravel(owner, "오래된 초대")
		val newestTravel = saveTravel(owner, "최신 초대")
		val middleTravel = saveTravel(owner, "중간 초대")
		val otherTravel = saveTravel(owner, "다른 사용자 초대")
		saveInvitation(oldestTravel, invitee, "2026-07-01T00:00:00Z")
		saveInvitation(newestTravel, invitee, "2026-07-03T00:00:00Z")
		saveInvitation(middleTravel, invitee, "2026-07-02T00:00:00Z")
		saveInvitation(otherTravel, otherInvitee, "2026-07-04T00:00:00Z")

		mockMvc.get("/api/v1/users/me/travel-invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(invitee))
			param("page", "0")
			param("size", "2")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.totalElements", equalTo(3))
				jsonPath("$.data.totalPages", equalTo(2))
				jsonPath("$.data.content[0].travel.title", equalTo("최신 초대"))
				jsonPath("$.data.content[1].travel.title", equalTo("중간 초대"))
				jsonPath("$.data.content[0].inviter.nickname", equalTo("list-owner"))
				jsonPath("$.data.content[0].status", equalTo("PENDING"))
			}

		mockMvc.get("/api/v1/users/me/travel-invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(invitee))
			param("page", "1")
			param("size", "2")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content.length()", equalTo(1))
				jsonPath("$.data.content[0].travel.title", equalTo("오래된 초대"))
			}
	}

	@Test
	fun `status filter is applied and deleted travel invitations are excluded`() {
		val owner = saveUser("filter-owner")
		val invitee = saveUser("filter-invitee")
		val rejectedTravel = saveTravel(owner, "거절한 초대")
		val deletedTravel = saveTravel(owner, "삭제된 여행 초대")
		val rejectedInvitation = saveInvitation(rejectedTravel, invitee, "2026-07-02T00:00:00Z")
		saveInvitation(deletedTravel, invitee, "2026-07-03T00:00:00Z")
		jdbcTemplate.update(
			"UPDATE planner_members SET status = 'REJECTED', responded_at = ? WHERE id = ?",
			Timestamp.from(Instant.parse("2026-07-04T00:00:00Z")),
			rejectedInvitation.id,
		)
		deletedTravel.softDelete(Instant.parse("2026-07-05T00:00:00Z"))
		travelRepository.saveAndFlush(deletedTravel)
		entityManager.clear()

		mockMvc.get("/api/v1/users/me/travel-invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(invitee))
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.totalElements", equalTo(0))
			}

		mockMvc.get("/api/v1/users/me/travel-invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(invitee))
			param("status", "REJECTED")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.totalElements", equalTo(1))
				jsonPath("$.data.content[0].travel.title", equalTo("거절한 초대"))
				jsonPath("$.data.content[0].status", equalTo("REJECTED"))
			}

		mockMvc.get("/api/v1/users/me/travel-invitations") {
			header(HttpHeaders.AUTHORIZATION, bearer(invitee))
			param("status", "UNKNOWN")
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
	}

	@Test
	fun `unauthenticated user cannot list received invitations`() {
		mockMvc.get("/api/v1/users/me/travel-invitations")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "received-invitation-${UUID.randomUUID()}",
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
		invitedAt: String,
	): TravelMember = travelMemberRepository.saveAndFlush(
		TravelMember(
			travel = travel,
			user = invitee,
			role = TravelRole.READ_ONLY,
			invitedAt = Instant.parse(invitedAt),
		),
	)
}
