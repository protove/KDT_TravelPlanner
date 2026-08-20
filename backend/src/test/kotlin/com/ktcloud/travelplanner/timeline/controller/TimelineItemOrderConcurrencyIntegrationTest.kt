package com.ktcloud.travelplanner.timeline.controller

import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdate
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdateRequest
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.timeline.service.TimelineItemOrderUpdateService
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.transaction.support.TransactionTemplate
import java.time.LocalDate
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@Import(TestcontainersConfiguration::class)
class TimelineItemOrderConcurrencyIntegrationTest(
	@Autowired private val timelineItemOrderUpdateService: TimelineItemOrderUpdateService,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val timelineItemRepository: TimelineItemRepository,
	@Autowired private val transactionTemplate: TransactionTemplate,
	@Autowired private val jdbcTemplate: JdbcTemplate,
) {
	@Test
	fun `concurrent same day reorders serialize without deadlock or duplicate orders`() {
		val owner = saveUser("concurrency-owner")
		val travel = saveTravel(owner)
		val items = (1..3).map { visitOrder -> saveItem(travel, visitOrder.toShort()) }
		val requests = listOf(
			items.asReversed(),
			listOf(items[1], items[2], items[0]),
		).map { orderedItems ->
			TimelineItemOrderUpdateRequest(
				dayNumber = 1,
				items = orderedItems.mapIndexed { index, item ->
					TimelineItemOrderUpdate(item.id, index + 1)
				},
			)
		}
		val ready = CountDownLatch(requests.size)
		val start = CountDownLatch(1)
		val executor = Executors.newFixedThreadPool(requests.size)

		try {
			val futures = requests.map { request ->
				executor.submit {
					ready.countDown()
					check(start.await(10, TimeUnit.SECONDS)) { "concurrency test did not start" }
					transactionTemplate.executeWithoutResult {
						timelineItemOrderUpdateService.updateTimelineItemOrder(
								travelId = travel.id,
								requesterId = requireNotNull(owner.id),
								request = request,
							)
					}
				}
			}
			assertTrue(ready.await(10, TimeUnit.SECONDS))
			start.countDown()
			futures.forEach { it.get(30, TimeUnit.SECONDS) }
		} finally {
			executor.shutdownNow()
			executor.awaitTermination(10, TimeUnit.SECONDS)
		}

		val persistedOrders = jdbcTemplate.query(
			"SELECT id, visit_order FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
			{ resultSet, _ ->
				resultSet.getObject("id", UUID::class.java) to resultSet.getShort("visit_order").toInt()
			},
			travel.id,
		)
		assertEquals(listOf(1, 2, 3), persistedOrders.map { it.second })
		assertEquals(items.map(TimelineItem::id).toSet(), persistedOrders.map { it.first }.toSet())
		val persistedMapping = persistedOrders.toMap()
		assertTrue(
			requests.any { request ->
				request.items.associate { item -> item.itemId to item.visitOrder } == persistedMapping
			},
		)
	}

	@Test
	fun `same day reorder waits for an existing row lock before committing`() {
		val owner = saveUser("lock-owner")
		val travel = saveTravel(owner)
		val items = (1..3).map { visitOrder -> saveItem(travel, visitOrder.toShort()) }
		val request = TimelineItemOrderUpdateRequest(
			dayNumber = 1,
			items = items.asReversed().mapIndexed { index, item ->
				TimelineItemOrderUpdate(item.id, index + 1)
			},
		)
		val executor = Executors.newSingleThreadExecutor()
		lateinit var blockedFuture: java.util.concurrent.Future<*>

		try {
			transactionTemplate.executeWithoutResult {
				jdbcTemplate.query(
					"SELECT id FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order FOR UPDATE",
					{ _, _ -> Unit },
					travel.id,
				)
				blockedFuture = executor.submit {
					transactionTemplate.executeWithoutResult {
						timelineItemOrderUpdateService.updateTimelineItemOrder(
							travelId = travel.id,
							requesterId = requireNotNull(owner.id),
							request = request,
						)
					}
				}
				assertFalse(blockedFuture.isDone)
				try {
					blockedFuture.get(1, TimeUnit.SECONDS)
					throw AssertionError("same-day reorder committed while the row lock was held")
				} catch (_: TimeoutException) {
					// Expected: the second transaction is waiting for the deterministic row lock.
				}
			}
			blockedFuture.get(30, TimeUnit.SECONDS)
		} finally {
			executor.shutdownNow()
			executor.awaitTermination(10, TimeUnit.SECONDS)
		}

		val persistedIds = jdbcTemplate.query(
			"SELECT id FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
			{ resultSet, _ -> resultSet.getObject("id", UUID::class.java) },
			travel.id,
		)
		assertEquals(items.asReversed().map(TimelineItem::id), persistedIds)
	}

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "timeline-order-concurrency-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "동시성 순서 테스트",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)

	private fun saveItem(travel: Travel, visitOrder: Short): TimelineItem = timelineItemRepository.saveAndFlush(
		TimelineItem(
			travel = travel,
			dayNumber = 1,
			visitDate = LocalDate.parse("2026-08-01"),
			category = TimelineCategory.OTHER,
			name = "동시성 순서 항목 $visitOrder",
			visitOrder = visitOrder,
		),
	)
}
