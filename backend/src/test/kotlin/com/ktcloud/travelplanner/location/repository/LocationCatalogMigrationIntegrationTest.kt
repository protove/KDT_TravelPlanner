package com.ktcloud.travelplanner.location.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.flywaydb.core.Flyway
import org.flywaydb.core.api.MigrationVersion
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.jdbc.core.JdbcTemplate
import javax.sql.DataSource
import kotlin.test.assertEquals

class LocationCatalogMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Autowired
	private lateinit var dataSource: DataSource

	@Test
	fun `empty database applies schema and versioned seed migrations`() {
		assertEquals(
			2,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM flyway_schema_history WHERE version IN ('2', '3') AND success = TRUE",
				Int::class.java,
			),
		)
		assertEquals(
			"Japan",
			jdbcTemplate.queryForObject("SELECT name_en FROM country_table WHERE id = 1", String::class.java),
		)
		assertEquals(
			"Tokyo",
			jdbcTemplate.queryForObject("SELECT name_en FROM city_table WHERE id = 10", String::class.java),
		)
	}

	@Test
	fun `current version one schema upgrades through location migrations`() {
		val schema = "location_upgrade_test"
		jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		jdbcTemplate.execute("CREATE SCHEMA $schema")

		try {
			Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("1"))
				.load()
				.migrate()

			val result = Flyway.configure()
				.dataSource(dataSource)
				.schemas(schema)
				.defaultSchema(schema)
				.target(MigrationVersion.fromVersion("3"))
				.load()
				.migrate()

			assertEquals(2, result.migrationsExecuted)
			assertEquals(
				2,
				jdbcTemplate.queryForObject(
					"SELECT COUNT(*) FROM $schema.flyway_schema_history WHERE version IN ('2', '3') AND success = TRUE",
					Int::class.java,
				),
			)
		} finally {
			jdbcTemplate.execute("DROP SCHEMA IF EXISTS $schema CASCADE")
		}
	}

	@Test
	fun `country code and city name uniqueness constraints reject duplicates`() {
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO country_table (id, code, name_ko, name_en) VALUES (99, 'JP', '중복', 'Duplicate')",
			)
		}

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO city_table (id, country_id, name_ko, name_en) VALUES (99, 1, '중복', 'Tokyo')",
			)
		}
	}

	@Test
	fun `foreign key and restrict delete preserve country ownership`() {
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO city_table (id, country_id, name_ko, name_en) VALUES (99, 999, '도시', 'City')",
			)
		}

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update("DELETE FROM country_table WHERE id = 1")
		}
	}

	@Test
	fun `coordinate and display order constraints reject invalid values`() {
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO city_table (id, country_id, name_ko, name_en, latitude) " +
					"VALUES (99, 1, '도시', 'Invalid Latitude', 90.000001)",
			)
		}

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO country_table (id, code, name_ko, name_en, display_order) " +
					"VALUES (99, 'ZZ', '국가', 'Country', -1)",
			)
		}
	}
}
