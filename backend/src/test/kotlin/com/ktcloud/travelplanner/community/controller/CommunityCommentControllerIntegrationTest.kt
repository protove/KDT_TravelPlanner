package com.ktcloud.travelplanner.community.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hamcrest.Matchers.equalTo
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.delete
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class CommunityCommentControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val communityCategoryRepository: CommunityCategoryRepository,
	@Autowired private val communityPostRepository: CommunityPostRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
) {
	private val objectMapper = ObjectMapper()

	@Test
	fun `unauthenticated user can list comments and receives an empty list for a fresh post`() {
		val author = saveUser("list-author")
		val post = savePost(author)

		mockMvc.get("/api/v1/community/posts/${post.id}/comments")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(0))
			}
	}

	@Test
	fun `listing comments for a nonexistent post returns 404`() {
		mockMvc.get("/api/v1/community/posts/${UUID.randomUUID()}/comments")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	@Test
	fun `authenticated user creates a comment and sees isMine true, others see isMine false`() {
		val author = saveUser("author")
		val commenter = saveUser("commenter")
		val other = saveUser("other")
		val post = savePost(author)

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(commenter))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "좋은 후기네요!"}"""
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.content", equalTo("좋은 후기네요!"))
			jsonPath("$.data.isMine", equalTo(true))
		}

		mockMvc.get("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(commenter))
		}.andExpect {
			jsonPath("$.data.length()", equalTo(1))
			jsonPath("$.data[0].content", equalTo("좋은 후기네요!"))
			jsonPath("$.data[0].isMine", equalTo(true))
		}

		mockMvc.get("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(other))
		}.andExpect {
			jsonPath("$.data[0].isMine", equalTo(false))
		}
	}

	@Test
	fun `unauthenticated comment creation returns 401`() {
		val author = saveUser("unauth-author")
		val post = savePost(author)

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "댓글"}"""
		}.andExpect {
			status { isUnauthorized() }
			jsonPath("$.code", equalTo("UNAUTHORIZED"))
		}
	}

	@Test
	fun `blank comment content is rejected with 400`() {
		val author = saveUser("blank-author")
		val post = savePost(author)

		mockMvc.post("/api/v1/community/posts/${post.id}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "   "}"""
		}.andExpect {
			status { isBadRequest() }
			jsonPath("$.code", equalTo("VALIDATION_ERROR"))
		}
	}

	@Test
	fun `comment creation on a nonexistent post returns 404`() {
		val author = saveUser("missing-post-author")

		mockMvc.post("/api/v1/community/posts/${UUID.randomUUID()}/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": "댓글"}"""
		}.andExpect {
			status { isNotFound() }
			jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
		}
	}

	@Test
	fun `comment author can delete their own comment and it disappears from the list`() {
		val author = saveUser("delete-author")
		val post = savePost(author)
		val commentId = createCommentViaApi(post.id, author, "지울 댓글")

		mockMvc.delete("/api/v1/community/comments/$commentId") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
		}.andExpect { status { isOk() } }

		mockMvc.get("/api/v1/community/posts/${post.id}/comments")
			.andExpect { jsonPath("$.data.length()", equalTo(0)) }
	}

	@Test
	fun `deleting another user's comment is forbidden`() {
		val author = saveUser("forbid-author")
		val other = saveUser("forbid-other")
		val post = savePost(author)
		val commentId = createCommentViaApi(post.id, author, "남의 댓글")

		mockMvc.delete("/api/v1/community/comments/$commentId") {
			header(HttpHeaders.AUTHORIZATION, bearer(other))
		}.andExpect {
			status { isForbidden() }
			jsonPath("$.code", equalTo("ACCESS_DENIED"))
		}
	}

	@Test
	fun `deleting a nonexistent comment returns 404`() {
		val author = saveUser("delete-404-author")

		mockMvc.delete("/api/v1/community/comments/${UUID.randomUUID()}") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
		}.andExpect {
			status { isNotFound() }
			jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
		}
	}

	private fun createCommentViaApi(
		postId: UUID,
		author: User,
		text: String,
	): UUID {
		val result = mockMvc.post("/api/v1/community/posts/$postId/comments") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
			contentType = MediaType.APPLICATION_JSON
			content = """{"content": ${objectMapper.writeValueAsString(text)}}"""
		}.andReturn()
		return UUID.fromString(
			Regex("\"commentId\":\"([^\"]+)\"").find(result.response.contentAsString)!!.groupValues[1],
		)
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(suffix: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "comment-$suffix-${UUID.randomUUID()}",
			email = "$suffix@example.com",
			name = suffix,
		),
	)

	private fun savePost(author: User): CommunityPost {
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue("TRAVEL_REVIEW")!!
		val bodyJson = objectMapper.readTree(
			"""{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"본문"}]}]}""",
		)
		val post = CommunityPost(
			author = author,
			category = category,
			title = "댓글 테스트용 게시글",
			bodyJson = bodyJson.toString(),
			bodyPreview = "본문",
			sourceTravelId = null,
		)
		return communityPostRepository.saveAndFlush(post)
	}
}
