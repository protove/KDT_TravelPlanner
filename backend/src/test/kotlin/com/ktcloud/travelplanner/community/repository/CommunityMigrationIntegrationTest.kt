package com.ktcloud.travelplanner.community.repository

import com.ktcloud.travelplanner.testsupport.ContainerIntegrationTestSupport
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.jdbc.core.JdbcTemplate
import kotlin.test.assertEquals
import kotlin.test.assertNull

class CommunityMigrationIntegrationTest : ContainerIntegrationTestSupport() {
	@Autowired
	private lateinit var jdbcTemplate: JdbcTemplate

	@Test
	fun `empty database applies community schema migrations`() {
		// V19는 커뮤니티와 무관한 타임라인 마이그레이션이라 의도적으로 제외한다(원래도 그랬음).
		assertEquals(
			9,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM flyway_schema_history " +
					"WHERE version IN ('13', '14', '15', '16', '17', '18', '20', '21', '22') AND success = TRUE",
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
	fun `deleting a post cascades to its tags, comments, reactions and comment reactions`() {
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
		val commentId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO community_comment (id, post_id, author_id, content, created_at) VALUES (?, ?, ?, '댓글', now())",
			commentId,
			postId,
			authorId,
		)
		jdbcTemplate.update(
			"INSERT INTO community_reaction (post_id, user_id, type) VALUES (?, ?, 'LIKE')",
			postId,
			authorId,
		)
		jdbcTemplate.update(
			"INSERT INTO community_comment_reaction (comment_id, user_id, type) VALUES (?, ?, 'LIKE')",
			commentId,
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
		// post -> comment -> comment_reaction으로 체이닝되는 ON DELETE CASCADE(V17 -> V20) 확인.
		assertEquals(
			0,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_comment_reaction WHERE comment_id = ?",
				Int::class.java,
				commentId,
			),
		)
	}

	@Test
	fun `comment reaction type is constrained to LIKE and rejects duplicate likes from the same user`() {
		val authorId = insertUser()
		val commentId = insertComment(insertPost(authorId), authorId)

		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO community_comment_reaction (comment_id, user_id, type) VALUES (?, ?, 'DISLIKE')",
				commentId,
				authorId,
			)
		}

		jdbcTemplate.update(
			"INSERT INTO community_comment_reaction (comment_id, user_id, type) VALUES (?, ?, 'LIKE')",
			commentId,
			authorId,
		)
		assertThrows<DataIntegrityViolationException> {
			jdbcTemplate.update(
				"INSERT INTO community_comment_reaction (comment_id, user_id, type) VALUES (?, ?, 'LIKE')",
				commentId,
				authorId,
			)
		}
	}

	@Test
	fun `community_post itinerary_snapshot_json defaults to null and can store a tiptap document`() {
		val authorId = insertUser()
		val postId = insertPost(authorId)

		assertNull(
			jdbcTemplate.queryForObject(
				"SELECT itinerary_snapshot_json FROM community_post WHERE id = ?",
				String::class.java,
				postId,
			),
		)

		jdbcTemplate.update(
			"UPDATE community_post SET itinerary_snapshot_json = '{\"type\":\"doc\"}'::jsonb WHERE id = ?",
			postId,
		)

		assertEquals(
			1,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_post WHERE id = ? AND itinerary_snapshot_json IS NOT NULL",
				Int::class.java,
				postId,
			),
		)
	}

	@Test
	fun `community_comment updated_at defaults to null and can be set on edit`() {
		val authorId = insertUser()
		val commentId = insertComment(insertPost(authorId), authorId)

		assertNull(
			jdbcTemplate.queryForObject(
				"SELECT updated_at FROM community_comment WHERE id = ?",
				java.sql.Timestamp::class.java,
				commentId,
			),
		)

		jdbcTemplate.update("UPDATE community_comment SET content = '수정됨', updated_at = now() WHERE id = ?", commentId)

		assertEquals(
			1,
			jdbcTemplate.queryForObject(
				"SELECT COUNT(*) FROM community_comment WHERE id = ? AND updated_at IS NOT NULL",
				Int::class.java,
				commentId,
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

	private fun insertPost(authorId: java.util.UUID): java.util.UUID {
		val postId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO community_post (id, author_id, category_id, title, body_json, created_at, updated_at) " +
				"VALUES (?, ?, 1, '제목', '{}'::jsonb, now(), now())",
			postId,
			authorId,
		)
		return postId
	}

	private fun insertComment(
		postId: java.util.UUID,
		authorId: java.util.UUID,
	): java.util.UUID {
		val commentId = java.util.UUID.randomUUID()
		jdbcTemplate.update(
			"INSERT INTO community_comment (id, post_id, author_id, content, created_at) VALUES (?, ?, ?, '댓글', now())",
			commentId,
			postId,
			authorId,
		)
		return commentId
	}
}
