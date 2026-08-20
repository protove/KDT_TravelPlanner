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
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
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
class TimelineItemOrderUpdateControllerIntegrationTest(
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
	fun `owner reorders all items without unique constraint conflicts`() {
		val owner = saveUser("order-owner")
		val travel = saveTravel(owner)
		val firstItem = saveItem(travel, 1, 1)
		val secondItem = saveItem(travel, 1, 2)
		val thirdItem = saveItem(travel, 1, 3)

		patchOrder(
			travel,
			owner,
			requestBody(1, thirdItem.id to 1, firstItem.id to 2, secondItem.id to 3),
		).andExpect { status { isOk() } }

		entityManager.clear()
		val reorderedItems = timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(travel.id, 1)
		assertEquals(listOf(thirdItem.id, firstItem.id, secondItem.id), reorderedItems.map(TimelineItem::id))
		assertEquals(listOf(1, 2, 3), reorderedItems.map { it.visitOrder.toInt() })
	}

	@Test
	fun `invalid permutations return bad request and leave all orders unchanged`() {
		val owner = saveUser("order-invalid-owner")
		val travel = saveTravel(owner)
		val otherTravel = saveTravel(owner)
		val firstItem = saveItem(travel, 1, 1)
		val secondItem = saveItem(travel, 1, 2)
		val thirdItem = saveItem(travel, 1, 3)
		val nextDayItem = saveItem(travel, 2, 1)
		val otherTravelItem = saveItem(otherTravel, 1, 1)
		val invalidBodies = listOf(
			requestBody(1, firstItem.id to 1, firstItem.id to 2, thirdItem.id to 3),
			requestBody(1, firstItem.id to 1, secondItem.id to 2),
			requestBody(1, firstItem.id to 1, secondItem.id to 2, nextDayItem.id to 3),
			requestBody(1, firstItem.id to 1, secondItem.id to 2, otherTravelItem.id to 3),
		)

		invalidBodies.forEach { body ->
			patchOrder(travel, owner, body)
				.andExpect {
					status { isBadRequest() }
					jsonPath("$.code", equalTo("INVALID_REQUEST"))
				}
		}

		entityManager.clear()
		val unchangedItems = timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(travel.id, 1)
		assertEquals(listOf(firstItem.id, secondItem.id, thirdItem.id), unchangedItems.map(TimelineItem::id))
		assertEquals(listOf(1, 2, 3), unchangedItems.map { it.visitOrder.toInt() })
	}

	@Test
	fun `read only member cannot reorder items`() {
		val owner = saveUser("order-access-owner")
		val readOnly = saveUser("order-read-only")
		val travel = saveTravel(owner)
		val item = saveItem(travel, 1, 1)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		patchOrder(travel, readOnly, requestBody(1, item.id to 1))
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
	}

	@Test
	fun `accepted read write member can reorder items`() {
		val owner = saveUser("order-read-write-owner")
		val readWrite = saveUser("order-read-write-member")
		val travel = saveTravel(owner)
		val firstItem = saveItem(travel, 1, 1)
		val secondItem = saveItem(travel, 1, 2)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)

		patchOrder(
			travel,
			readWrite,
			requestBody(1, secondItem.id to 1, firstItem.id to 2),
		).andExpect { status { isOk() } }

		entityManager.clear()
		val reorderedItems = timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(travel.id, 1)
		assertEquals(listOf(secondItem.id, firstItem.id), reorderedItems.map(TimelineItem::id))
	}

	@Test
	fun `missing travel returns not found`() {
		val owner = saveUser("order-missing-travel-owner")
		patchOrderById(
			UUID.randomUUID(),
			owner,
			requestBody(1, UUID.randomUUID() to 1),
		).andExpect {
			status { isNotFound() }
			jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
		}
	}

	@Test
	fun `anonymous reorder returns unauthorized`() {
		mockMvc.patch("/api/v1/travels/${UUID.randomUUID()}/timeline-items/order") {
			contentType = MediaType.APPLICATION_JSON
			content = requestBody(1, UUID.randomUUID() to 1)
		}.andExpect { status { isUnauthorized() } }
	}

	private fun patchOrder(
		travel: Travel,
		requester: User,
		body: String,
	) = patchOrderById(travel.id, requester, body)

	private fun patchOrderById(
		travelId: UUID,
		requester: User,
		body: String,
	) = mockMvc.patch("/api/v1/travels/$travelId/timeline-items/order") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		contentType = MediaType.APPLICATION_JSON
		content = body
	}

	private fun requestBody(
		dayNumber: Int,
		vararg items: Pair<UUID, Int>,
	): String =
		"""
		{
		  "dayNumber": $dayNumber,
		  "items": [
		    ${items.joinToString(",\n    ") { (itemId, visitOrder) ->
			"""{"itemId":"$itemId","visitOrder":$visitOrder}"""
		}}
		  ]
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
			name = "순서 테스트 일정",
			visitOrder = visitOrder,
		),
	)

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "timeline-order-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "타임라인 순서 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
