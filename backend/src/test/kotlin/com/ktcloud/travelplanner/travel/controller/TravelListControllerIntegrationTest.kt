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
import java.sql.Timestamp
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelListControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `lists only owned and accepted travels ordered by update time with keyword and pages`() {
		val requester = saveUser("list-requester")
		val otherOwner = saveUser("list-other-owner")
		val owned = saveTravel(requester, "Tokyo Owner", OWNED_ID)
		val accepted = saveTravel(otherOwner, "Tokyo Shared", ACCEPTED_ID)
		val pending = saveTravel(otherOwner, "Tokyo Pending", PENDING_ID)
		val outsider = saveTravel(otherOwner, "Tokyo Outsider", OUTSIDER_ID)
		val deleted = saveTravel(requester, "Tokyo Deleted", DELETED_ID)

		acceptMembership(accepted, requester, TravelRole.READ_WRITE)
		travelMemberRepository.saveAndFlush(
			TravelMember(
				travel = pending,
				user = requester,
				role = TravelRole.READ_ONLY,
				invitedAt = Instant.parse("2026-01-01T00:00:00Z"),
			),
		)
		updateTravel(owned.id, "2026-01-01T00:00:00Z")
		updateTravel(accepted.id, "2026-01-03T00:00:00Z")
		updateTravel(pending.id, "2026-01-05T00:00:00Z")
		updateTravel(outsider.id, "2026-01-06T00:00:00Z")
		updateTravel(deleted.id, "2026-01-07T00:00:00Z", deleted = true)
		entityManager.clear()

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "tokyo")
			param("page", "0")
			param("size", "1")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(ACCEPTED_ID.toString()))
				jsonPath("$.data.content[0].permission", equalTo("READ_WRITE"))
				jsonPath("$.data.page", equalTo(0))
				jsonPath("$.data.size", equalTo(1))
				jsonPath("$.data.totalElements", equalTo(2))
				jsonPath("$.data.totalPages", equalTo(2))
				jsonPath("$.data.isFirst", equalTo(true))
				jsonPath("$.data.isLast", equalTo(false))
			}

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "Tokyo")
			param("page", "1")
			param("size", "1")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(OWNED_ID.toString()))
				jsonPath("$.data.content[0].permission", equalTo("OWNER"))
				jsonPath("$.data.isLast", equalTo(true))
			}
	}

	@Test
	fun `rejects unauthenticated and invalid pagination requests`() {
		mockMvc.get("/api/v1/travels")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}

		val requester = saveUser("invalid-page-requester")
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("page", "-1")
			param("size", "101")
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
	}

	@Test
	fun `lists owned travel when keyword parameter is omitted`() {
		val requester = saveUser("no-keyword-requester")
		val travel = saveTravel(requester, "검색어 없는 목록", UUID.randomUUID())

		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.content[0].travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.totalElements", equalTo(1))
			}
	}

	private fun acceptMembership(
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
		jdbcTemplate.update(
			"UPDATE planner_members SET status = 'ACCEPTED', responded_at = ? WHERE id = ?",
			Timestamp.from(Instant.parse("2026-01-02T00:00:00Z")),
			member.id,
		)
	}

	private fun updateTravel(
		travelId: UUID,
		updatedAt: String,
		deleted: Boolean = false,
	) {
		jdbcTemplate.update(
			"UPDATE planners_table SET updated_at = ?, deleted_at = ? WHERE id = ?",
			Timestamp.from(Instant.parse(updatedAt)),
			if (deleted) Timestamp.from(Instant.parse(updatedAt)) else null,
			travelId,
		)
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "list-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(
		owner: User,
		title: String,
		travelId: UUID,
	): Travel = travelRepository.saveAndFlush(
		Travel(
			id = travelId,
			owner = owner,
			title = title,
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-04"),
		),
	)

	companion object {
		private val OWNED_ID = UUID.fromString("00000000-0000-0000-0000-000000000180")
		private val ACCEPTED_ID = UUID.fromString("00000000-0000-0000-0000-000000000181")
		private val PENDING_ID = UUID.fromString("00000000-0000-0000-0000-000000000182")
		private val OUTSIDER_ID = UUID.fromString("00000000-0000-0000-0000-000000000183")
		private val DELETED_ID = UUID.fromString("00000000-0000-0000-0000-000000000184")
	}
}
