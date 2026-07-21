package com.ktcloud.travelplanner.travel.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.hasSize
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

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelDetailControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val timelineItemRepository: TimelineItemRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `owner receives travel detail with timeline sorted by day and order`() {
		val owner = saveUser("detail-owner")
		val travel = saveTravel(owner)
		saveTimelineItem(travel, 2, "2026-08-02", 1, "2일차 첫 일정")
		saveTimelineItem(travel, 1, "2026-08-01", 2, "1일차 두 번째 일정")
		saveTimelineItem(travel, 1, "2026-08-01", 1, "1일차 첫 일정")

		getDetail(travel, owner)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.ownerId", equalTo(owner.id.toString()))
				jsonPath("$.data.title", equalTo("상세 여행"))
				jsonPath("$.data.travelDays", equalTo(3))
				jsonPath("$.data.permission", equalTo("OWNER"))
				jsonPath("$.data.timelineItems", hasSize<Any>(3))
				jsonPath("$.data.timelineItems[0].name", equalTo("1일차 첫 일정"))
				jsonPath("$.data.timelineItems[0].latitude") { doesNotExist() }
				jsonPath("$.data.timelineItems[0].longitude") { doesNotExist() }
				jsonPath("$.data.timelineItems[0].rating") { doesNotExist() }
				jsonPath("$.data.timelineItems[1].name", equalTo("1일차 두 번째 일정"))
				jsonPath("$.data.timelineItems[2].name", equalTo("2일차 첫 일정"))
			}
	}

	@Test
	fun `accepted read write and read only participants receive their permission`() {
		val owner = saveUser("detail-access-owner")
		val readWrite = saveUser("detail-read-write")
		val readOnly = saveUser("detail-read-only")
		val travel = saveTravel(owner)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		getDetail(travel, readWrite)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.permission", equalTo("READ_WRITE"))
			}
		getDetail(travel, readOnly)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.permission", equalTo("READ_ONLY"))
			}
	}

	@Test
	fun `non participant is forbidden and deleted travel is not found`() {
		val owner = saveUser("detail-denied-owner")
		val outsider = saveUser("detail-outsider")
		val travel = saveTravel(owner)

		getDetail(travel, outsider)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}

		jdbcTemplate.update("UPDATE planners_table SET deleted_at = NOW() WHERE id = ?", travel.id)
		entityManager.clear()
		getDetail(travel, owner)
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	private fun getDetail(
		travel: Travel,
		requester: User,
	) = mockMvc.get("/api/v1/travels/${travel.id}") {
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

	private fun saveTimelineItem(
		travel: Travel,
		dayNumber: Short,
		visitDate: String,
		visitOrder: Short,
		name: String,
	) {
		timelineItemRepository.saveAndFlush(
			TimelineItem(
				travel = travel,
				dayNumber = dayNumber,
				visitDate = LocalDate.parse(visitDate),
				category = TimelineCategory.OTHER,
				name = name,
				visitOrder = visitOrder,
			),
		)
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "detail-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "상세 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
