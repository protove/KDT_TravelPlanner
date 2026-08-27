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
import org.hamcrest.Matchers.notNullValue
import org.hamcrest.Matchers.nullValue
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
import org.springframework.test.web.servlet.delete
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
	fun `GET me posts hides the requester's own soft deleted posts by default`() {
		val requester = saveUser("me-posts-deleted-requester")
		val kept = savePost(requester, "안 지운 글")
		val deleted = savePost(requester, "내가 지운 글")
		setCreatedAt(kept.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(deleted.id, Instant.parse("2026-08-02T00:00:00Z"))

		mockMvc.delete("/api/v1/community/posts/${deleted.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/me/posts") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].title", equalTo("안 지운 글"))
			jsonPath("$.data.content[0].deletedAt", nullValue())
		}
	}

	@Test
	fun `GET me posts includeDeleted=true includes the requester's own soft deleted posts with deletedAt set`() {
		val requester = saveUser("me-posts-include-deleted-requester")
		val kept = savePost(requester, "안 지운 글")
		val deleted = savePost(requester, "내가 지운 글")
		setCreatedAt(kept.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(deleted.id, Instant.parse("2026-08-02T00:00:00Z"))

		mockMvc.delete("/api/v1/community/posts/${deleted.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/me/posts") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("includeDeleted", "true")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(2))
			jsonPath("$.data.content[0].title", equalTo("내가 지운 글"))
			jsonPath("$.data.content[0].deletedAt", notNullValue())
			jsonPath("$.data.content[1].title", equalTo("안 지운 글"))
			jsonPath("$.data.content[1].deletedAt", nullValue())
		}
	}

	@Test
	fun `GET me posts filters by keyword across title and body preview`() {
		val requester = saveUser("me-posts-keyword-requester")
		val matchesTitle = savePost(requester, "부산 여행 후기")
		val other = savePost(requester, "완전 무관한 글")
		setCreatedAt(matchesTitle.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(other.id, Instant.parse("2026-08-02T00:00:00Z"))

		mockMvc.get("/api/v1/community/me/posts") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "부산")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].postId", equalTo(matchesTitle.id.toString()))
		}
	}

	@Test
	fun `GET me posts filters by periodStart and periodEnd against createdAt`() {
		val requester = saveUser("me-posts-period-requester")
		val inside = savePost(requester, "기간 안")
		val outside = savePost(requester, "기간 밖")
		setCreatedAt(inside.id, Instant.parse("2026-08-15T00:00:00Z"))
		setCreatedAt(outside.id, Instant.parse("2026-09-15T00:00:00Z"))

		mockMvc.get("/api/v1/community/me/posts") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("periodStart", "2026-08-01")
			param("periodEnd", "2026-08-31")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].postId", equalTo(inside.id.toString()))
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
	fun `GET me comments hides comments on a soft deleted post by default`() {
		val requester = saveUser("me-comments-deleted-post-requester")
		val post = savePost(requester, "곧 삭제될 글")

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "삭제될 글에 단 댓글"}"""
		}.andExpect { status { isOk() } }

		// entityManager.clear()는 아직 flush되지 않은 변경분(방금 만든 댓글의 insert)을 커밋 없이
		// 그냥 버려버린다 — 테스트 전체가 @Transactional 하나로 묶여 있어 위 POST의 persist()가
		// 자동으로 flush되는 시점(커밋)이 오지 않기 때문. clear() 전에 명시적으로 flush해서
		// 댓글이 실제로 DB에 반영된 뒤에 지운다(같은 클래스의 CommunityPost soft-delete 시나리오와
		// 동일한 함정).
		entityManager.flush()
		jdbcTemplate.update("UPDATE community_post SET deleted_at = NOW() WHERE id = ?", post.id)
		entityManager.clear()

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(0))
		}

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("includeDeleted", "true")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].postTitle", equalTo("곧 삭제될 글"))
			jsonPath("$.data.content[0].deletedAt", nullValue())
			jsonPath("$.data.content[0].postDeletedAt", notNullValue())
		}
	}

	@Test
	fun `GET me comments hides the requester's own soft deleted comment by default`() {
		val requester = saveUser("me-comments-own-deleted-requester")
		val post = savePost(requester, "댓글 달릴 글")

		val response = mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "지울 댓글"}"""
		}.andExpect { status { isOk() } }.andReturn()
		val commentId = objectMapper.readTree(response.response.contentAsString)["data"]["commentId"].asText()

		mockMvc.delete("/api/v1/community/comments/$commentId") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(0))
		}

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("includeDeleted", "true")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].content", equalTo("지울 댓글"))
			jsonPath("$.data.content[0].deletedAt", notNullValue())
		}
	}

	@Test
	fun `GET me comments filters by keyword across content and post title`() {
		val requester = saveUser("me-comments-keyword-requester")
		val post = savePost(requester, "부산 여행기")

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "완전 무관한 댓글"}"""
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "부산")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.totalElements", equalTo(1))
			jsonPath("$.data.content[0].postTitle", equalTo("부산 여행기"))
		}

		mockMvc.get("/api/v1/community/me/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(requester))
			param("keyword", "전혀-매치안됨")
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
