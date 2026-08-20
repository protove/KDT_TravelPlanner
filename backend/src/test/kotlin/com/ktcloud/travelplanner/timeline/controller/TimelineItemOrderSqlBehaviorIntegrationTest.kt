package com.ktcloud.travelplanner.timeline.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
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
import jakarta.persistence.EntityManagerFactory
import org.hibernate.SessionFactory
import org.hibernate.stat.Statistics
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.TestPropertySource
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.patch
import org.springframework.transaction.annotation.Transactional
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@TestPropertySource(properties = ["spring.jpa.properties.hibernate.generate_statistics=true"])
@Transactional
class TimelineItemOrderSqlBehaviorIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val timelineItemRepository: TimelineItemRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
	@Autowired private val entityManagerFactory: EntityManagerFactory,
) {
	@Test
	fun `noop has no entity updates while reverse produces repeated flush updates`() {
		val noopOwner = saveUser("sql-noop-owner")
		val noopTravel = saveTravel(noopOwner, "noop")
		val noopItems = saveItems(noopTravel, 10)
		entityManager.flush()
		entityManager.clear()

		val statistics = entityManagerFactory.unwrap(SessionFactory::class.java).statistics
		statistics.clear()
		patchOrder(noopTravel, noopOwner, requestBody(noopItems))
			.andExpect { status { isOk() } }
		val noopSnapshot = snapshot(statistics)

		val reverseOwner = saveUser("sql-reverse-owner")
		val reverseTravel = saveTravel(reverseOwner, "reverse")
		val reverseItems = saveItems(reverseTravel, 10)
		entityManager.flush()
		entityManager.clear()

		statistics.clear()
		patchOrder(reverseTravel, reverseOwner, requestBody(reverseItems.asReversed()))
			.andExpect { status { isOk() } }
		val reverseSnapshot = snapshot(statistics)

		assertEquals(0L, noopSnapshot.entityUpdateCount)
		assertTrue(reverseSnapshot.entityUpdateCount >= 3L)
		assertTrue(reverseSnapshot.flushCount > noopSnapshot.flushCount)
		assertTrue(reverseSnapshot.prepareStatementCount > noopSnapshot.prepareStatementCount)
	}

	private fun snapshot(statistics: Statistics): Snapshot = Snapshot(
		entityUpdateCount = statistics.entityUpdateCount,
		flushCount = statistics.flushCount,
		prepareStatementCount = statistics.prepareStatementCount,
	)

	private fun patchOrder(travel: Travel, owner: User, body: String) =
		mockMvc.patch("/api/v1/travels/${travel.id}/timeline-items/order") {
			header(HttpHeaders.AUTHORIZATION, "Bearer ${jwtTokenService.issueAccessToken(requireNotNull(owner.id)).value}")
			contentType = MediaType.APPLICATION_JSON
			content = body
		}

	private fun requestBody(items: List<TimelineItem>): String =
		"""
		{
		  "dayNumber": 1,
		  "items": [
		    ${items.mapIndexed { index, item -> "{\"itemId\":\"${item.id}\",\"visitOrder\":${index + 1}}" }.joinToString(",\n    ")}
		  ]
		}
		""".trimIndent()

	private fun saveItems(travel: Travel, count: Int): List<TimelineItem> =
		(1..count).map { visitOrder ->
			timelineItemRepository.saveAndFlush(
				TimelineItem(
					travel = travel,
					dayNumber = 1,
					visitDate = LocalDate.parse("2026-08-01"),
					category = TimelineCategory.OTHER,
					name = "SQL diagnostics $visitOrder",
					visitOrder = visitOrder.toShort(),
				),
			)
		}

	private fun saveTravel(owner: User, suffix: String): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "SQL diagnostics $suffix",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "sql-diagnostic-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private data class Snapshot(
		val entityUpdateCount: Long,
		val flushCount: Long,
		val prepareStatementCount: Long,
	)
}
