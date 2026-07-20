package com.ktcloud.travelplanner.timeline.controller

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
import org.hamcrest.Matchers.nullValue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TimelineItemUpdateControllerIntegrationTest(
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
	fun `owner partially updates item and clears nullable fields`() {
		val owner = saveUser("timeline-update-owner")
		val travel = saveTravel(owner)
		val item = saveItem(travel, 1, 1, TimelineCategory.FOOD, "수정 전 일정", "일식")

		patchItem(
			travel,
			item,
			owner,
			"""
			{
			  "category": "기타",
			  "foodSubcategory": null,
			  "name": "수정 후 일정",
			  "googlePlaceId": null,
			  "latitude": null,
			  "longitude": null,
			  "rating": null,
			  "memo": null
			}
			""".trimIndent(),
		)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.name", equalTo("수정 후 일정"))
				jsonPath("$.data.category", equalTo("기타"))
				jsonPath("$.data.foodSubcategory", nullValue())
				jsonPath("$.data.memo", nullValue())
			}
	}

	@Test
	fun `read write can update while read only is forbidden`() {
		val owner = saveUser("timeline-update-access-owner")
		val readWrite = saveUser("timeline-update-read-write")
		val readOnly = saveUser("timeline-update-read-only")
		val travel = saveTravel(owner)
		val item = saveItem(travel, 1, 1)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		patchItem(travel, item, readWrite, """{"memo":"공동 수정"}""")
			.andExpect { status { isOk() } }
		patchItem(travel, item, readOnly, """{"memo":"거부"}""")
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `item from another travel is not found and duplicate order is conflict`() {
		val owner = saveUser("timeline-update-conflict-owner")
		val travel = saveTravel(owner)
		val otherTravel = saveTravel(owner)
		val item = saveItem(travel, 1, 1)
		saveItem(travel, 1, 2)

		patchItem(otherTravel, item, owner, """{"memo":"잘못된 플랜"}""")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
		patchItem(travel, item, owner, """{"visitOrder":2}""")
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	private fun patchItem(
		travel: Travel,
		item: TimelineItem,
		requester: User,
		body: String,
	) = mockMvc.patch("/api/v1/travels/${travel.id}/timeline-items/${item.id}") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = body
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

	private fun saveItem(
		travel: Travel,
		dayNumber: Short,
		visitOrder: Short,
		category: TimelineCategory = TimelineCategory.OTHER,
		name: String = "타임라인 일정",
		foodSubcategory: String? = null,
	): TimelineItem = timelineItemRepository.saveAndFlush(
		TimelineItem(
			travel = travel,
			dayNumber = dayNumber,
			visitDate = travel.startDate.plusDays(dayNumber.toLong() - 1),
			category = category,
			foodSubcategory = foodSubcategory,
			name = name,
			visitOrder = visitOrder,
			memo = "기존 메모",
		),
	)

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "timeline-update-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "타임라인 수정 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
