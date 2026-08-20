package com.ktcloud.travelplanner.timeline.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.transaction.support.TransactionTemplate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.UUID
import kotlin.test.assertEquals

class TimelineItemOrderRepositoryIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var timelineItemOrderRepository: TimelineItemOrderRepository

	@Autowired
	private lateinit var transactionTemplate: TransactionTemplate

	@Test
	fun `locked snapshot is ordered and one bulk update changes the exact rows`() {
		val fixture = fixture(3)
		lateinit var snapshot: List<TimelineItemOrderSnapshot>

		transactionTemplate.executeWithoutResult {
			snapshot = timelineItemOrderRepository.findLockedByTravelIdAndDayNumber(fixture.travelId, 1)
			assertEquals(fixture.itemIds, snapshot.map(TimelineItemOrderSnapshot::itemId))
			assertEquals(listOf(1, 2, 3), snapshot.map { it.visitOrder.toInt() })
			timelineItemOrderRepository.updateVisitOrders(
				travelId = fixture.travelId,
				dayNumber = 1,
				itemIds = fixture.itemIds.asReversed(),
				visitOrders = listOf(1, 2, 3).map(Int::toShort),
			)
		}

		assertEquals(
			fixture.itemIds.asReversed(),
			jdbcTemplate.query(
				"SELECT id FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
				{ resultSet, _ -> resultSet.getObject("id", UUID::class.java) },
				fixture.travelId,
			),
		)
	}

	@Test
	fun `update count mismatch rolls back the entire transaction`() {
		val fixture = fixture(3)
		val missingItemId = UUID.randomUUID()

		assertThrows<RuntimeException> {
			transactionTemplate.executeWithoutResult {
				timelineItemOrderRepository.updateVisitOrders(
					travelId = fixture.travelId,
					dayNumber = 1,
					itemIds = fixture.itemIds + missingItemId,
					visitOrders = listOf(1, 2, 3, 4).map(Int::toShort),
				)
			}
		}

		assertEquals(
			listOf(1, 2, 3),
			jdbcTemplate.query(
				"SELECT visit_order FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
				{ resultSet, _ -> resultSet.getShort("visit_order").toInt() },
				fixture.travelId,
			),
		)
	}

	@Test
	fun `caller failure after bulk update rolls back the complete order change`() {
		val fixture = fixture(3)

		assertThrows<RuntimeException> {
			transactionTemplate.executeWithoutResult {
				timelineItemOrderRepository.updateVisitOrders(
					travelId = fixture.travelId,
					dayNumber = 1,
					itemIds = fixture.itemIds.asReversed(),
					visitOrders = listOf(1, 2, 3).map(Int::toShort),
				)
				throw IllegalStateException("forced post-update failure")
			}
		}

		assertEquals(
			listOf(1, 2, 3),
			jdbcTemplate.query(
				"SELECT visit_order FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
				{ resultSet, _ -> resultSet.getShort("visit_order").toInt() },
				fixture.travelId,
			),
		)
	}

	@Test
	fun `deferred unique violation at immediate check rolls back the complete order change`() {
		val fixture = fixture(3)

		assertThrows<RuntimeException> {
			transactionTemplate.executeWithoutResult {
				timelineItemOrderRepository.updateVisitOrders(
					travelId = fixture.travelId,
					dayNumber = 1,
					itemIds = fixture.itemIds,
					visitOrders = listOf(1, 1, 3).map(Int::toShort),
				)
			}
		}

		assertEquals(
			listOf(1, 2, 3),
			jdbcTemplate.query(
				"SELECT visit_order FROM timeline_table WHERE planner_id = ? AND day_number = 1 ORDER BY visit_order",
				{ resultSet, _ -> resultSet.getShort("visit_order").toInt() },
				fixture.travelId,
			),
		)
	}

	private fun fixture(itemCount: Int): Fixture {
		val ownerId = UUID.randomUUID()
		val travelId = UUID.randomUUID()
		val now = OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC)
		jdbcTemplate.update(
			"INSERT INTO user_table (id, provider, provider_user_id, profile_completed, created_at, updated_at) " +
				"VALUES (?, 'GOOGLE', ?, FALSE, ?, ?)",
			ownerId,
			"timeline-order-repository-$ownerId",
			now,
			now,
		)
		jdbcTemplate.update(
			"INSERT INTO planners_table " +
				"(id, owner_id, title, start_date, end_date, created_at, updated_at) " +
				"VALUES (?, ?, 'Repository order test', '2026-08-01', '2026-08-03', ?, ?)",
			travelId,
			ownerId,
			now,
			now,
		)
		val itemIds = (1..itemCount).map { visitOrder ->
			val itemId = UUID.randomUUID()
			jdbcTemplate.update(
				"INSERT INTO timeline_table " +
					"(id, planner_id, day_number, visit_date, category, name, visit_order) " +
					"VALUES (?, ?, 1, '2026-08-01', '기타', ?, ?)",
				itemId,
				travelId,
				"Repository item $visitOrder",
				visitOrder,
			)
			itemId
		}
		return Fixture(travelId, itemIds)
	}

	private data class Fixture(
		val travelId: UUID,
		val itemIds: List<UUID>,
	)
}
