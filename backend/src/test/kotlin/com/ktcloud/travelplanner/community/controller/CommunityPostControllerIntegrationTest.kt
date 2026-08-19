package com.ktcloud.travelplanner.community.controller

import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.model.CommunityCategory
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.notNullValue
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
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class CommunityPostControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val communityPostRepository: CommunityPostRepository,
	@Autowired private val communityCategoryRepository: CommunityCategoryRepository,
	@Autowired private val communityTagRepository: CommunityTagRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	private val objectMapper = ObjectMapper()


	@Test
	fun `authenticated user creates a travel review post and links find-or-create tags`() {
		val author = saveUser("author")
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(author.id)).value
		communityTagRepository.saveAndFlush(CommunityTag(name = "부산"))

		val result = mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """
				{
					"categoryCode": "TRAVEL_REVIEW",
					"title": "부산 여행 후기",
					"bodyJson": {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"좋았어요"}]}]},
					"tags": ["부산", "신규태그"]
				}
			""".trimIndent()
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.postId", notNullValue())
			}
			.andReturn()

		val postId = UUID.fromString(
			Regex("\"postId\":\"([^\"]+)\"").find(result.response.contentAsString)!!.groupValues[1],
		)
		val post = communityPostRepository.findById(postId).orElseThrow()
		assertEquals("부산 여행 후기", post.title)
		assertEquals("좋았어요", post.bodyPreview)
		assertEquals(setOf("부산", "신규태그"), post.tags.map { it.name }.toSet())
	}

	@Test
	fun `unauthenticated create request returns unauthorized`() {
		mockMvc.post("/api/v1/community/posts") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"categoryCode":"TRAVEL_REVIEW","title":"t","bodyJson":{"type":"doc"}}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	@Test
	fun `category outside TRAVEL_REVIEW scope is rejected`() {
		val author = saveUser("scope-author")
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(author.id)).value

		mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"categoryCode":"FREE","title":"t","bodyJson":{"type":"doc"}}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
			}

		assertEquals(0, communityPostRepository.count())
	}

	@Test
	fun `bodyJson outside the tiptap whitelist is rejected with 400`() {
		val author = saveUser("body-author")
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(author.id)).value

		mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"categoryCode":"TRAVEL_REVIEW","title":"t","bodyJson":{"type":"codeBlock"}}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
			}

		assertEquals(0, communityPostRepository.count())
	}

	@Test
	fun `sourceTravelId is rejected with 403 when the requester has no accepted access`() {
		val owner = saveUser("owner")
		val outsider = saveUser("outsider")
		val travel = saveTravel(owner)
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(outsider.id)).value

		mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """
				{
					"categoryCode": "TRAVEL_REVIEW",
					"title": "t",
					"bodyJson": {"type":"doc"},
					"sourceTravelId": "${travel.id}"
				}
			""".trimIndent()
		}
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}

		assertEquals(0, communityPostRepository.count())
	}

	@Test
	fun `sourceTravelId is accepted for a member with accepted read access`() {
		val owner = saveUser("owner2")
		val member = saveUser("member2")
		val travel = saveTravel(owner)
		val travelMember = TravelMember(
			travel = travel,
			user = member,
			role = TravelRole.READ_ONLY,
			invitedAt = Instant.now(),
		)
		travelMember.respond(TravelInvitationAction.ACCEPT, Instant.now())
		travelMemberRepository.saveAndFlush(travelMember)
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(member.id)).value

		mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """
				{
					"categoryCode": "TRAVEL_REVIEW",
					"title": "동행 후기",
					"bodyJson": {"type":"doc"},
					"sourceTravelId": "${travel.id}"
				}
			""".trimIndent()
		}
			.andExpect { status { isOk() } }

		assertTrue(communityPostRepository.findAll().any { it.sourceTravelId == travel.id })
	}

	@Test
	fun `anonymous request returns post detail with isMine false and increments view count`() {
		val author = saveUser("detail-author")
		val post = savePost(author, tags = setOf("부산"))

		mockMvc.get("/api/v1/community/posts/${post.id}")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.postId", equalTo(post.id.toString()))
				jsonPath("$.data.categoryCode", equalTo("TRAVEL_REVIEW"))
				jsonPath("$.data.title", equalTo("상세 조회 테스트"))
				jsonPath("$.data.tags[0]", equalTo("부산"))
				jsonPath("$.data.authorNickname", equalTo(author.nickname))
				jsonPath("$.data.viewCount", equalTo(1))
				jsonPath("$.data.commentCount", equalTo(0))
				jsonPath("$.data.reactionCount", equalTo(0))
				jsonPath("$.data.bodyJson.type", equalTo("doc"))
				jsonPath("$.data.isMine", equalTo(false))
			}

		mockMvc.get("/api/v1/community/posts/${post.id}")
			.andExpect { jsonPath("$.data.viewCount", equalTo(2)) }
	}

	@Test
	fun `authenticated author sees isMine true, other users see isMine false`() {
		val author = saveUser("detail-owner")
		val other = saveUser("detail-other")
		val post = savePost(author)

		mockMvc.get("/api/v1/community/posts/${post.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(author))
		}.andExpect { jsonPath("$.data.isMine", equalTo(true)) }

		mockMvc.get("/api/v1/community/posts/${post.id}") {
			header(HttpHeaders.AUTHORIZATION, bearer(other))
		}.andExpect { jsonPath("$.data.isMine", equalTo(false)) }
	}

	@Test
	fun `returns 404 for a nonexistent post and for a soft deleted post`() {
		mockMvc.get("/api/v1/community/posts/${UUID.randomUUID()}")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}

		val author = saveUser("detail-deleted-author")
		val post = savePost(author)
		jdbcTemplate.update("UPDATE community_post SET deleted_at = NOW() WHERE id = ?", post.id)
		entityManager.clear()

		mockMvc.get("/api/v1/community/posts/${post.id}")
			.andExpect {
				status { isNotFound() }
				jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
			}
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun savePost(
		author: User,
		tags: Set<String> = emptySet(),
	): CommunityPost {
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue("TRAVEL_REVIEW")!!
		val bodyJson = objectMapper.readTree(
			"""{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"본문"}]}]}""",
		)
		val post = CommunityPost(
			author = author,
			category = category,
			title = "상세 조회 테스트",
			bodyJson = bodyJson.toString(),
			bodyPreview = "본문",
			sourceTravelId = null,
		)
		post.assignTags(tags.map { name -> communityTagRepository.findByName(name) ?: saveTag(name) }.toSet())
		return communityPostRepository.saveAndFlush(post)
	}

	private fun saveTag(name: String): CommunityTag {
		communityTagRepository.insertIgnoringConflict(name)
		return communityTagRepository.findByName(name)!!
	}

	private fun saveUser(suffix: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "community-$suffix-${UUID.randomUUID()}",
			email = "$suffix@example.com",
			name = suffix,
		),
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "테스트 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-04"),
		),
	)
}
