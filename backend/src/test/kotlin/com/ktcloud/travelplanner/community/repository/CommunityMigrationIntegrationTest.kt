package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.jdbc.core.JdbcTemplate
import kotlin.test.assertEquals

class CommunityMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Test
	fun `empty database applies community schema migrations`() {
		assertEquals(
			6,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM flyway_schema_history " +
					"WHERE version IN ('13', '14', '15', '16', '17', '18') AND success = TRUE",
				Int::class.java,
			),
		)
	}

	@Test
	fun `community category seed data matches the four expected rows`() {
		assertEquals(
			4,
			jdbcTemplate.queryForObject("SELECT COUNT(*) FROM community_category", Int::class.java),
		)
		assertEquals(
			listOf("TRAVEL_REVIEW", "FREE", "QNA", "NOTICE"),
			jdbcTemplate.queryForList(
				"SELECT code FROM community_category ORDER BY sort_order",
				String::class.java,
			),
		)
	}

	@Test
	fun `category code uniqueness and tag name uniqueness reject duplicates`() {
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO community_category (id, code, name, sort_order) VALUES (99, 'FREE', '중복', 5)",
			)
		}

		jdbcTemplate.update("INSERT INTO community_tag (name) VALUES ('제주도')")
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update("INSERT INTO community_tag (name) VALUES ('제주도')")
		}
	}

	@Test
	fun `deleting a category referenced by a post is restricted`() {
		val authorId = insertUser()
		val postId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO community_post (id, author_id, category_id, title, body_json, created_at, updated_at) " +
				"VALUES (?, ?, 1, '제목', '{}'::jsonb, now(), now())",
			postId,
			authorId,
		)

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update("DELETE FROM community_category WHERE id = 1")
		}
	}

	@Test
	fun `deleting a post cascades to its tags, comments and reactions`() {
		val authorId = insertUser()
		val postId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO community_post (id, author_id, category_id, title, body_json, created_at, updated_at) " +
				"VALUES (?, ?, 1, '제목', '{}'::jsonb, now(), now())",
			postId,
			authorId,
		)
		val tagId = jdbcTemplate.queryForObject(
			"INSERT INTO community_tag (name) VALUES ('오사카') RETURNING id",
			Long::class.java,
		)
		jdbcTemplate.update(
			"INSERT INTO community_post_tag (post_id, tag_id) VALUES (?, ?)",
			postId,
			tagId,
		)
		jdbcTemplate.update(
			"INSERT INTO community_comment (id, post_id, author_id, content, created_at) VALUES (?, ?, ?, '댓글', now())",
			java.util.UUID.randomUUID(),
			postId,
			authorId,
		)
		jdbcTemplate.update(
			"INSERT INTO community_reaction (post_id, user_id, type) VALUES (?, ?, 'LIKE')",
			postId,
			authorId,
		)

		jdbcTemplate.update("DELETE FROM community_post WHERE id = ?", postId)

		assertEquals(
			0,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_post_tag WHERE post_id = ?",
				Int::class.java,
				postId,
			),
		)
		assertEquals(
			0,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_comment WHERE post_id = ?",
				Int::class.java,
				postId,
			),
		)
		assertEquals(
			0,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_reaction WHERE post_id = ?",
				Int::class.java,
				postId,
			),
		)
	}

	private fun insertUser(): java.util.UUID {
		val userId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO user_table (id, provider, provider_user_id, created_at, updated_at) " +
				"VALUES (?, 'GOOGLE', ?, now(), now())",
			userId,
			userId.toString(),
		)
		return userId
	}
}
