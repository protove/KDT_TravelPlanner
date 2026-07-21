package com.ktcloud.travelplanner.timeline.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
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
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.post
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
class TimelineItemControllerIntegrationTest(
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
	fun `owner creates timeline item persisted with api category value`() {
		val owner = saveUser("timeline-owner")
		val travel = saveTravel(owner)

		postTimelineItem(travel, owner, validRequest())
			.andExpect {
				status { isOk() }
				jsonPath("$.data.timelineItemId", notNullValue())
			}

		entityManager.flush()
		entityManager.clear()
		val item = timelineItemRepository.findAll().single()
		assertEquals(travel.id, item.travel.id)
		assertEquals(1, item.dayNumber?.toInt())
		assertEquals(LocalDate.parse("2026-08-01"), item.visitDate)
		assertEquals(TimelineCategory.FOOD, item.category)
		assertEquals("일식", item.foodSubcategory)
		assertEquals(
			"음식",
			jdbcTemplate.queryForObject(
				"SELECT category FROM timeline_table WHERE id = ?",
				String::class.java,
				item.id,
			),
		)
	}

	@Test
	fun `accepted read write member can create and read only member is forbidden`() {
		val owner = saveUser("timeline-access-owner")
		val readWrite = saveUser("timeline-read-write")
		val readOnly = saveUser("timeline-read-only")
		val travel = saveTravel(owner)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		postTimelineItem(travel, readWrite, validRequest())
			.andExpect { status { isOk() } }
		postTimelineItem(travel, readOnly, validRequest(visitOrder = 2))
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `out of range date mismatched day and duplicate order are rejected`() {
		val owner = saveUser("timeline-validation-owner")
		val travel = saveTravel(owner)

		postTimelineItem(
			travel,
			owner,
			validRequest(dayNumber = 4, visitDate = "2026-08-04"),
		)
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}
		postTimelineItem(
			travel,
			owner,
			validRequest(dayNumber = 2, visitDate = "2026-08-01"),
		)
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("INVALID_REQUEST"))
			}

		postTimelineItem(travel, owner, validRequest())
			.andExpect { status { isOk() } }
		postTimelineItem(travel, owner, validRequest())
			.andExpect {
				status { isConflict() }
				jsonPath("$.code", equalTo("CONFLICT"))
			}
	}

	private fun postTimelineItem(
		travel: Travel,
		requester: User,
		requestBody: String,
	) = mockMvc.post("/api/v1/travels/${travel.id}/timeline-items") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = requestBody
	}

	private fun validRequest(
		dayNumber: Int = 1,
		visitDate: String = "2026-08-01",
		visitOrder: Int = 1,
	): String =
		"""
		{
		  "dayNumber": $dayNumber,
		  "visitDate": "$visitDate",
		  "cityId": null,
		  "category": "음식",
		  "foodSubcategory": "일식",
		  "name": "도쿄 스시",
		  "googlePlaceId": "google-place-id",
		  "latitude": 35.658581,
		  "longitude": 139.745433,
		  "rating": 4.5,
		  "visitOrder": $visitOrder,
		  "memo": "저녁 방문"
		}
		""".trimIndent()

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
			providerUserId = "timeline-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "타임라인 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
