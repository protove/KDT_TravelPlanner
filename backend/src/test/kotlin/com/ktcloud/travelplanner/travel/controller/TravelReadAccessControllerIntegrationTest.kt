package com.ktcloud.travelplanner.travel.controller

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
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

// MSA 전환용 내부 API GET /api/v1/travels/{travelId}/read-access 의 계약 회귀 테스트.
// community 등 다른 서비스가 이 응답으로 TravelAccessPort.exists / hasReadAccess 를 채운다.
@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelReadAccessControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner has read access`() {
		val owner = saveUser("read-access-owner")
		val travel = saveTravel(owner)

		getReadAccess(travel.id, owner)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.exists", equalTo(true))
				jsonPath("$.data.hasReadAccess", equalTo(true))
			}
	}

	@Test
	fun `accepted member has read access, outsider exists but is denied`() {
		val owner = saveUser("read-access-member-owner")
		val member = saveUser("read-access-member")
		val outsider = saveUser("read-access-outsider")
		val travel = saveTravel(owner)
		acceptMember(travel, member, TravelRole.READ_ONLY)

		getReadAccess(travel.id, member)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.exists", equalTo(true))
				jsonPath("$.data.hasReadAccess", equalTo(true))
			}
		getReadAccess(travel.id, outsider)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.exists", equalTo(true))
				jsonPath("$.data.hasReadAccess", equalTo(false))
			}
	}

	@Test
	fun `missing or soft deleted travel reports exists false`() {
		val requester = saveUser("read-access-missing")

		getReadAccess(UUID.randomUUID(), requester)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.exists", equalTo(false))
				jsonPath("$.data.hasReadAccess", equalTo(false))
			}

		val owner = saveUser("read-access-deleted-owner")
		val travel = saveTravel(owner)
		jdbcTemplate.update("UPDATE planners_table SET deleted_at = NOW() WHERE id = ?", travel.id)
		entityManager.clear()
		getReadAccess(travel.id, owner)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.exists", equalTo(false))
				jsonPath("$.data.hasReadAccess", equalTo(false))
			}
	}

	@Test
	fun `unauthenticated request is rejected`() {
		mockMvc.get("/api/v1/travels/${UUID.randomUUID()}/read-access")
			.andExpect { status { isUnauthorized() } }
	}

	private fun getReadAccess(
		travelId: UUID,
		requester: User,
	) = mockMvc.get("/api/v1/travels/$travelId/read-access") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
	}

	private fun acceptMember(
		travel: Travel,
		user: User,
		role: TravelRole,
	) {
		val member = travelMemberRepository.saveAndFlush(
			TravelMember(
				travel = travel,
				user = user,
				role = role,
				invitedAt = Instant.parse("2026-01-01T00:00:00Z"),
			),
		)
		jdbcTemplate.update("UPDATE planner_members SET status = 'ACCEPTED' WHERE id = ?", member.id)
		entityManager.clear()
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "read-access-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "권한 확인 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
