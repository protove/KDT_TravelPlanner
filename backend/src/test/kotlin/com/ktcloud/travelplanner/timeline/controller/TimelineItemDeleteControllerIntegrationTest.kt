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
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TimelineItemDeleteControllerIntegrationTest(
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
	fun `owner deletes item and compacts only the same day visit orders`() {
		val owner = saveUser("timeline-delete-owner")
		val travel = saveTravel(owner)
		val firstItem = saveItem(travel, 1, 1)
		val deletedItem = saveItem(travel, 1, 2)
		val thirdItem = saveItem(travel, 1, 3)
		val nextDayItem = saveItem(travel, 2, 1)

		deleteItem(travel, deletedItem, owner)
			.andExpect {
				status { isOk() }
				jsonPath("$.data", equalTo(emptyMap<String, Any>()))
			}

		entityManager.clear()
		assertFalse(timelineItemRepository.existsById(deletedItem.id))
		val remainingItems = timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(travel.id)
		assertEquals(listOf(firstItem.id, thirdItem.id, nextDayItem.id), remainingItems.map(TimelineItem::id))
		assertEquals(listOf(1, 2, 1), remainingItems.map { it.visitOrder.toInt() })
	}

	@Test
	fun `read write can delete while read only is forbidden`() {
		val owner = saveUser("timeline-delete-access-owner")
		val readWrite = saveUser("timeline-delete-read-write")
		val readOnly = saveUser("timeline-delete-read-only")
		val travel = saveTravel(owner)
		val readWriteItem = saveItem(travel, 1, 1)
		val readOnlyItem = saveItem(travel, 1, 2)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		deleteItem(travel, readWriteItem, readWrite).andExpect { status { isOk() } }
		deleteItem(travel, readOnlyItem, readOnly)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `item from another travel is not found`() {
		val owner = saveUser("delete-not-found-owner")
		val travel = saveTravel(owner)
		val otherTravel = saveTravel(owner)
		val item = saveItem(travel, 1, 1)

		deleteItem(otherTravel, item, owner)
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}

		assertEquals(true, timelineItemRepository.existsById(item.id))
	}

	private fun deleteItem(
		travel: Travel,
		item: TimelineItem,
		requester: User,
	) = mockMvc.delete("/api/v1/travels/${travel.id}/timeline-items/${item.id}") {
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

	private fun saveItem(
		travel: Travel,
		dayNumber: Short,
		visitOrder: Short,
	): TimelineItem = timelineItemRepository.saveAndFlush(
		TimelineItem(
			travel = travel,
			dayNumber = dayNumber,
			visitDate = travel.startDate.plusDays(dayNumber.toLong() - 1),
			category = TimelineCategory.OTHER,
			name = "삭제 테스트 일정",
			visitOrder = visitOrder,
		),
	)

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "timeline-delete-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "타임라인 삭제 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
