package com.ktcloud.travelplanner.timeline.repository

import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.stereotype.Repository
import java.sql.PreparedStatement
import java.util.UUID

@Repository
class JdbcTimelineItemOrderRepository(
	private val jdbcTemplate: JdbcTemplate,
) : TimelineItemOrderRepository {
	override fun findLockedByTravelIdAndDayNumber(
		travelId: UUID,
		dayNumber: Short,
	): List<TimelineItemOrderSnapshot> = jdbcTemplate.query(
		LOCKED_SNAPSHOT_SQL,
		{ resultSet, _ ->
			TimelineItemOrderSnapshot(
				itemId = resultSet.getObject("id", UUID::class.java),
				visitOrder = resultSet.getShort("visit_order"),
			)
		},
		travelId,
		dayNumber,
	)

	override fun updateVisitOrders(
		travelId: UUID,
		dayNumber: Short,
		itemIds: List<UUID>,
		visitOrders: List<Short>,
	) {
		require(itemIds.isNotEmpty()) { "itemIds must not be empty." }
		require(itemIds.size == visitOrders.size) { "itemIds and visitOrders must have the same size." }

		jdbcTemplate.execute(DEFER_ORDER_CONSTRAINT_SQL)
		val updatedRowCount = jdbcTemplate.update { connection ->
			connection.prepareStatement(BULK_UPDATE_SQL).apply {
				setArray(1, connection.createArrayOf("uuid", itemIds.map(UUID::toString).toTypedArray()))
				setArray(2, connection.createArrayOf("int2", visitOrders.map(Short::toString).toTypedArray()))
				setObject(3, travelId)
				setShort(4, dayNumber)
			}
		}
		check(updatedRowCount == itemIds.size) {
			"Timeline order update affected $updatedRowCount rows, expected ${itemIds.size}."
		}
		jdbcTemplate.execute(IMMEDIATE_ORDER_CONSTRAINT_SQL)
	}

	private companion object {
		val LOCKED_SNAPSHOT_SQL =
			"""
			SELECT id, visit_order
			FROM timeline_table
			WHERE planner_id = ?
			  AND day_number = ?
			ORDER BY visit_order ASC, id ASC
			FOR UPDATE
			""".trimIndent()

		const val DEFER_ORDER_CONSTRAINT_SQL =
			"SET CONSTRAINTS uq_timeline_planner_day_order DEFERRED"

		val BULK_UPDATE_SQL =
			"""
			UPDATE timeline_table AS timeline_item
			SET visit_order = requested.visit_order
			FROM unnest(?::uuid[], ?::smallint[]) AS requested(item_id, visit_order)
			WHERE timeline_item.id = requested.item_id
			  AND timeline_item.planner_id = ?
			  AND timeline_item.day_number = ?
			""".trimIndent()

		const val IMMEDIATE_ORDER_CONSTRAINT_SQL =
			"SET CONSTRAINTS uq_timeline_planner_day_order IMMEDIATE"
	}
}
