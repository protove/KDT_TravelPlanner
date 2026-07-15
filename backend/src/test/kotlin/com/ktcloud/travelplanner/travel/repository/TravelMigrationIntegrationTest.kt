package com.ktcloud.travelplanner.travel.repository

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

class TravelMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var dataSource: DataSource

	@Test
	fun `migration creates planner schema with version and ownership constraints`() {
		assertEquals(
			1,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM flyway_schema_history WHERE version = '4' AND success = TRUE",
				Int::class.java,
			),
		)
		assertEquals(
			0L,
			jdbcTemplate.queryForObject(
				"SELECT column_default FROM information_schema.columns " +
					"WHERE table_name = 'planners_table' AND column_name = 'version'",
				String::class.java,
			)?.toLong(),
		)
	}

	@Test
	fun `current location schema upgrades through planner migration`() {
		val schema = "travel_upgrade_test"
		jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		jdbcTemplate.execute("CREATE SCHEMA $schema")

		try {
			Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("3"))
				.load()
				.migrate()

			val result = Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("4"))
				.load()
				.migrate()

			assertEquals(1, result.migrationsExecuted)
			assertEquals(
				1,
				jdbcTemplate.queryForObject(
					"SELECT COUNT(*) FROM $schema.flyway_schema_history WHERE version = '4' AND success = TRUE",
					Int::class.java,
				),
			)
		} finally {
			jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		}
	}

	@Test
	fun `foreign key and date constraints reject invalid planner rows`() {
		val now = OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC)

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO planners_table " +
					"(id, owner_id, title, start_date, end_date, created_at, updated_at) " +
					"VALUES (?, ?, ?, ?, ?, ?, ?)",
				UUID.randomUUID(),
				UUID.randomUUID(),
				"소유자 없음",
				java.sql.Date.valueOf("2026-08-01"),
				java.sql.Date.valueOf("2026-08-04"),
				now,
				now,
			)
		}

		val ownerId = UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO user_table (id, provider, provider_user_id, profile_completed, created_at, updated_at) " +
				"VALUES (?, 'GOOGLE', ?, FALSE, ?, ?)",
			ownerId,
			"migration-owner-$ownerId",
			now,
			now,
		)
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO planners_table " +
					"(id, owner_id, title, start_date, end_date, created_at, updated_at) " +
					"VALUES (?, ?, ?, ?, ?, ?, ?)",
				UUID.randomUUID(),
				ownerId,
				"역순 여행",
				java.sql.Date.valueOf("2026-08-04"),
				java.sql.Date.valueOf("2026-08-01"),
				now,
				now,
			)
		}
	}
}
