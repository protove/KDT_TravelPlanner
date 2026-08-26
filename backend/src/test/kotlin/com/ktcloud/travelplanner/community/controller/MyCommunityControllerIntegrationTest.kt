package com.ktcloud.travelplanner.community.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityCommentRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.sql.Timestamp
import java.time.Instant
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class MyCommunityControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val communityPostRepository: CommunityPostRepository,
	@Autowired private val communityCommentRepository: CommunityCommentRepository,
	@Autowired private val communityCategoryRepository: CommunityCategoryRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	private val objectMapper = ObjectMapper()

	@Test
	fun `GET me posts returns only the requester's own posts ordered by createdAt desc`() {
		val requester = saveUser("me-posts-requester")
		val other = saveUser("me-posts-other")
		val first = savePost(requester, "내 글 1")
		val second = savePost(requester, "내 글 2")
		savePost(other, "남의 글")
		setCreatedAt(first.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(second.id, Instant.parse("2026-08-02T00:00:00Z"))

		mockMvc.get("/api/v1/community/me/posts") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(2))
			jsonPath("$.data.content[0].title", equalTo("내 글 2"))
			jsonPath("$.data.content[1].title", equalTo("내 글 1"))
		}
	}

	@Test
	fun `GET me posts requires authentication`() {
		mockMvc.get("/api/v1/community/me/posts")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `GET me comments returns only the requester's own comments with post context`() {
		val requester = saveUser("me-comments-requester")
		val other = saveUser("me-comments-other")
		val post = savePost(other, "댓글 달릴 글")

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "내가 쓴 댓글"}"""
		}.andExpect { status { isOk() } }

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(other))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "남이 쓴 댓글"}"""
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].content", equalTo("내가 쓴 댓글"))
			jsonPath("$.data.content[0].postId", equalTo(post.id.toString()))
			jsonPath("$.data.content[0].postTitle", equalTo("댓글 달릴 글"))
		}
	}

	@Test
	fun `GET me comments excludes comments on a soft deleted post`() {
		val requester = saveUser("me-comments-deleted-requester")
		val post = savePost(requester, "곧 삭제될 글")

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "삭제될 글에 단 댓글"}"""
		}.andExpect { status { isOk() } }

		jdbcTemplate.update("UPDATE community_post SET deleted_at = NOW() WHERE id = ?", post.id)
		entityManager.clear()

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(0))
		}
	}

	@Test
	fun `GET me comments requires authentication`() {
		mockMvc.get("/api/v1/community/me/comments")
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun setCreatedAt(
		postId: UUID,
		createdAt: Instant,
	) {
		jdbcTemplate.update("UPDATE community_post SET created_at = ? WHERE id = ?", Timestamp.from(createdAt), postId)
		entityManager.clear()
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(suffix: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "me-community-$suffix-${UUID.randomUUID()}",
			email = "$suffix@example.com",
			name = suffix,
		),
	)

	private fun savePost(
		author: User,
		title: String,
	): CommunityPost {
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue("TRAVEL_REVIEW")!!
		val bodyJson = objectMapper.readTree(
			"""{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"본문"}]}]}""",
		)
		val post = CommunityPost(
			author = author,
			category = category,
			title = title,
			bodyJson = bodyJson.toString(),
			bodyPreview = "본문",
			sourceTravelId = null,
			itinerarySnapshotJson = null,
		)
		return communityPostRepository.saveAndFlush(post)
	}
}
