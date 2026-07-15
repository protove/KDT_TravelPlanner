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
import org.springframework.test.web.servlet.delete
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelDeletionControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner soft deletes travel and repeated deletion returns not found`() {
		val owner = saveUser("delete-owner")
		val travel = saveTravel(owner)

		mockMvc.delete("/api/v1/travels/${travel.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
		}
			.andExpect { status { isOk() } }

		entityManager.clear()
		assertTrue(
			jdbcTemplate.queryForObject(
				"SELECT deleted_at IS NOT NULL FROM planners_table WHERE id = ?",
				Boolean::class.java,
				travel.id,
			) == true,
		)
		mockMvc.get("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.totalElements", equalTo(0))
			}
		mockMvc.delete("/api/v1/travels/${travel.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
		}
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	@Test
	fun `read only read write and unauthenticated users cannot delete travel`() {
		val owner = saveUser("delete-access-owner")
		val readOnly = saveUser("delete-read-only")
		val readWrite = saveUser("delete-read-write")
		val travel = saveTravel(owner)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)

		listOf(readOnly, readWrite).forEach { member ->
			mockMvc.delete("/api/v1/travels/${travel.id}") {
				header(HttpHeaders.AUTHORIZATION, bearer(member))
			}
				.andExpect {
					status { isForbidden() }
					jsonPath("$.code", equalTo("ACCESS_DENIED"))
				}
		}
		mockMvc.delete("/api/v1/travels/${travel.id}")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
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
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "delete-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "삭제 대상 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-04"),
		),
	)
}
