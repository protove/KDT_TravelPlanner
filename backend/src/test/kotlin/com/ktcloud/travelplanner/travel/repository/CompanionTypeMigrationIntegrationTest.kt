package com.ktcloud.travelplanner.travel.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import com.ktcloud.travelplanner.travel.model.CompanionType
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

class CompanionTypeMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var dataSource: DataSource

	@Test
	fun `V8 replaces the companion type constraint and preserves GROUP as ETC`() {
		val schema = "companion_type_upgrade_test"
		val ownerId = UUID.randomUUID()
		val existingTravelId = UUID.randomUUID()
		val now = OffsetDateTime.of(2026, 1, 1, 0, 0, 0, 0, ZoneOffset.UTC)
		jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		jdbcTemplate.execute("CREATE SCHEMA $schema")

		try {
			Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("7"))
				.load()
				.migrate()
			insertUser(schema, ownerId, now)
			insertTravel(schema, existingTravelId, ownerId, "GROUP", now)

			val result = Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("8"))
				.load()
				.migrate()

			assertEquals(1, result.migrationsExecuted)
			assertEquals(
				"ETC",
				jdbcTemplate.queryForObject(
					"SELECT companion_type FROM $schema.planners_table WHERE id = ?",
					String::class.java,
					existingTravelId,
				),
			)
			CompanionType.entries.forEach { companionType ->
				insertTravel(schema, UUID.randomUUID(), ownerId, companionType.name, now)
			}
			assertThrows<DataIntegrityViolationException> {
				insertTravel(schema, UUID.randomUUID(), ownerId, "GROUP", now)
			}
		} finally {
			jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		}
	}

	private fun insertUser(schema: String, ownerId: UUID, now: OffsetDateTime) {
		jdbcTemplate.update(
			"INSERT INTO $schema.user_table " +
				"(id, provider, provider_user_id, profile_completed, created_at, updated_at) " +
				"VALUES (?, 'GOOGLE', ?, FALSE, ?, ?)",
			ownerId,
			"companion-type-owner-$ownerId",
			now,
			now,
		)
	}

	private fun insertTravel(
		schema: String,
		travelId: UUID,
		ownerId: UUID,
		companionType: String,
		now: OffsetDateTime,
	) {
		jdbcTemplate.update(
			"INSERT INTO $schema.planners_table " +
				"(id, owner_id, title, start_date, end_date, companion_type, created_at, updated_at) " +
				"VALUES (?, ?, '동행자 유형 여행', '2026-08-01', '2026-08-02', ?, ?, ?)",
			travelId,
			ownerId,
			companionType,
			now,
			now,
		)
	}
}
