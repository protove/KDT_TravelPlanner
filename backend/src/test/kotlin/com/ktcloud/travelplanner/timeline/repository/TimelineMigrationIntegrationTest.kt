package com.ktcloud.travelplanner.timeline.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.flywaydb.core.Flyway
import org.flywaydb.core.api.MigrationVersion
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.jdbc.core.JdbcTemplate
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.UUID
import javax.sql.DataSource
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class TimelineMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var dataSource: DataSource

	@Test
	fun `current membership schema upgrades through timeline migration`() {
		val schema = "timeline_upgrade_test"
		jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		jdbcTemplate.execute("CREATE SCHEMA $schema")

		try {
			Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("5"))
				.load()
				.migrate()

			val result = Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("6"))
				.load()
				.migrate()

			assertEquals(1, result.migrationsExecuted)
			assertEquals(
				1,
				jdbcTemplate.queryForObject(
					"SELECT COUNT(*) FROM $schema.flyway_schema_history WHERE version = '6' AND success = TRUE",
					Int::class.java,
				),
			)
		} finally {
			jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		}
	}

	@Test
	fun `category bounds and daily order constraints reject invalid rows`() {
		val ownerId = UUID.randomUUID()
		val travelId = UUID.randomUUID()
		val now = OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC)
		jdbcTemplate.update(
			"INSERT INTO user_table (id, provider, provider_user_id, profile_completed, created_at, updated_at) " +
				"VALUES (?, 'GOOGLE', ?, FALSE, ?, ?)",
			ownerId,
			"timeline-owner-$ownerId",
			now,
			now,
		)
		jdbcTemplate.update(
			"INSERT INTO planners_table " +
				"(id, owner_id, title, start_date, end_date, created_at, updated_at) " +
				"VALUES (?, ?, '타임라인 여행', '2026-08-01', '2026-08-03', ?, ?)",
			travelId,
			ownerId,
			now,
			now,
		)

		insertTimelineItem(travelId, "관광지", null)
		assertThrows<DataIntegrityViolationException> {
			insertTimelineItem(travelId, "관광지", null)
		}
		assertThrows<DataIntegrityViolationException> {
			insertTimelineItem(travelId, "관광지", "일식", 2)
		}
	}

	@Test
	fun `timeline place persistence upgrades to identity only`() {
		val columns = jdbcTemplate.queryForList(
			"SELECT column_name FROM information_schema.columns WHERE table_name = 'timeline_table'",
			String::class.java,
		)
		assertFalse(columns.contains("latitude"))
		assertFalse(columns.contains("longitude"))
		assertFalse(columns.contains("rating"))
		assertEquals(
			"text",
			jdbcTemplate.queryForObject(
				"SELECT data_type FROM information_schema.columns " +
					"WHERE table_name = 'timeline_table' AND column_name = 'google_place_id'",
				String::class.java,
			),
		)
	}

	@Test
	fun `version eight schema upgrades existing timeline data to version nine`() {
		val schema = "timeline_place_identity_upgrade_test"
		jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		jdbcTemplate.execute("CREATE SCHEMA $schema")

		try {
			Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("8"))
				.load()
				.migrate()
			val ownerId = UUID.randomUUID()
			val travelId = UUID.randomUUID()
			val timelineItemId = UUID.randomUUID()
			val now = OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC)
			jdbcTemplate.update(
				"INSERT INTO $schema.user_table " +
					"(id, provider, provider_user_id, profile_completed, created_at, updated_at) " +
					"VALUES (?, 'GOOGLE', ?, FALSE, ?, ?)",
				ownerId,
				"timeline-upgrade-$ownerId",
				now,
				now,
			)
			jdbcTemplate.update(
				"INSERT INTO $schema.planners_table " +
					"(id, owner_id, title, start_date, end_date, created_at, updated_at) " +
					"VALUES (?, ?, '타임라인 마이그레이션', '2026-08-01', '2026-08-03', ?, ?)",
				travelId,
				ownerId,
				now,
				now,
			)
			jdbcTemplate.update(
				"INSERT INTO $schema.timeline_table " +
					"(id, planner_id, day_number, visit_date, category, name, google_place_id, latitude, " +
					"longitude, rating, visit_order) VALUES (?, ?, 1, '2026-08-01', '관광지', " +
					"'도쿄 타워', 'google-place-id', 35.658581, 139.745433, 4.5, 1)",
				timelineItemId,
				travelId,
			)

			val result = Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("9"))
				.load()
				.migrate()

			assertEquals(1, result.migrationsExecuted)
			assertEquals(
				"google-place-id",
				jdbcTemplate.queryForObject(
					"SELECT google_place_id FROM $schema.timeline_table WHERE id = ?",
					String::class.java,
					timelineItemId,
				),
			)
			assertEquals(
				0,
				jdbcTemplate.queryForObject(
					"SELECT COUNT(*) FROM information_schema.columns " +
						"WHERE table_schema = ? AND table_name = 'timeline_table' " +
						"AND column_name IN ('latitude', 'longitude', 'rating')",
					Int::class.java,
					schema,
				),
			)
		} finally {
			jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		}
	}

	private fun insertTimelineItem(
		travelId: UUID,
		category: String,
		foodSubcategory: String?,
		visitOrder: Int = 1,
	) {
		jdbcTemplate.update(
			"INSERT INTO timeline_table " +
				"(id, planner_id, day_number, visit_date, category, food_subcategory, name, visit_order) " +
				"VALUES (?, ?, 1, '2026-08-01', ?, ?, ?, ?)",
			UUID.randomUUID(),
			travelId,
			category,
			foodSubcategory,
			"도쿄 타워",
			visitOrder,
		)
	}
}
