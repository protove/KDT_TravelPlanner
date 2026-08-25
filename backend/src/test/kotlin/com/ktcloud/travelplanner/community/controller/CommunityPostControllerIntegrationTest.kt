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
import org.springframework.test.web.servlet.get
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.sql.Timestamp
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
	fun `post created with an itinerary snapshot returns it unchanged on detail lookup`() {
		// itinerarySnapshotJson은 bodyJson과 달리 Tiptap 문서가 아니라, 일정 자체의 원래 모양
		// (day별 장소 목록 + 좌표)을 프론트가 작성 시점에 조립해서 보내는 불변 값이다 — 백엔드는
		// 화이트리스트 검증 없이 그대로 저장/반환만 한다([[project_community_itinerary_snapshot]]).
		val author = saveUser("snapshot-author")
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(author.id)).value
		val travel = saveTravel(author)

		val result = mockMvc.post("/api/v1/community/posts") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """
				{
					"categoryCode": "TRAVEL_REVIEW",
					"title": "스냅샷 포함 후기",
					"bodyJson": {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"자유 작성"}]}]},
					"sourceTravelId": "${travel.id}",
					"itinerarySnapshotJson": {
						"title": "제주도 여행",
						"startDate": "2026-01-01",
						"endDate": "2026-01-03",
						"days": [
							{
								"dayNumber": 1,
								"visitDate": "2026-01-01",
								"items": [
									{
										"timelineItemId": "11111111-1111-1111-1111-111111111111",
										"name": "제주공항 도착",
										"category": "교통",
										"visitOrder": 1,
										"lat": 33.5066,
										"lng": 126.4930
									}
								]
							}
						]
					}
				}
			""".trimIndent()
		}
			.andExpect { status { isOk() } }
			.andReturn()

		val postId = UUID.fromString(
			Regex("\"postId\":\"([^\"]+)\"").find(result.response.contentAsString)!!.groupValues[1],
		)

		mockMvc.get("/api/v1/community/posts/$postId")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.bodyJson.content[0].content[0].text", equalTo("자유 작성"))
				jsonPath("$.data.itinerarySnapshotJson.title", equalTo("제주도 여행"))
				jsonPath("$.data.itinerarySnapshotJson.days[0].dayNumber", equalTo(1))
				jsonPath("$.data.itinerarySnapshotJson.days[0].items[0].name", equalTo("제주공항 도착"))
				jsonPath("$.data.itinerarySnapshotJson.days[0].items[0].lat", equalTo(33.5066))
			}
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
				jsonPath("$.data.itinerarySnapshotJson", nullValue())
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

	@Test
	fun `list endpoint filters by category, tag, and keyword and defaults to createdAt desc order`() {
		val author = saveUser("list-author")
		val busan = savePost(author, tags = setOf("부산"), title = "부산 여행 후기")
		val jeju = savePost(author, tags = setOf("제주"), title = "제주 여행 후기")
		val free = savePost(author, title = "자유 게시글", categoryCode = "FREE")
		setCreatedAt(busan.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(jeju.id, Instant.parse("2026-08-02T00:00:00Z"))
		setCreatedAt(free.id, Instant.parse("2026-08-03T00:00:00Z"))

		mockMvc.get("/api/v1/community/posts") {
			param("category", "TRAVEL_REVIEW")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.content.length()", equalTo(2))
			jsonPath("$.data.content[0].title", equalTo("제주 여행 후기"))
			jsonPath("$.data.content[1].title", equalTo("부산 여행 후기"))
			jsonPath("$.data.content[0].reactionCount", equalTo(0))
			jsonPath("$.data.content[0].commentCount", equalTo(0))
			jsonPath("$.data.totalElements", equalTo(2))
			jsonPath("$.data.page", equalTo(0))
			jsonPath("$.data.size", equalTo(10))
			jsonPath("$.data.isFirst", equalTo(true))
			jsonPath("$.data.isLast", equalTo(true))
		}

		mockMvc.get("/api/v1/community/posts") {
			param("tag", "부산")
		}.andExpect {
			jsonPath("$.data.content.length()", equalTo(1))
			jsonPath("$.data.content[0].title", equalTo("부산 여행 후기"))
			jsonPath("$.data.content[0].tags[0]", equalTo("부산"))
		}

		mockMvc.get("/api/v1/community/posts") {
			param("keyword", "자유")
		}.andExpect {
			jsonPath("$.data.content.length()", equalTo(1))
			jsonPath("$.data.content[0].title", equalTo("자유 게시글"))
		}
	}

	@Test
	fun `list endpoint accepts sort=popular without authentication and clamps size above 50`() {
		val author = saveUser("popular-author")
		val older = savePost(author, title = "오래된 글")
		val newer = savePost(author, title = "최신 글")
		setCreatedAt(older.id, Instant.parse("2026-08-01T00:00:00Z"))
		setCreatedAt(newer.id, Instant.parse("2026-08-05T00:00:00Z"))

		mockMvc.get("/api/v1/community/posts") {
			param("sort", "popular")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.content[0].title", equalTo("최신 글"))
			jsonPath("$.data.content[1].title", equalTo("오래된 글"))
		}

		mockMvc.get("/api/v1/community/posts") {
			param("size", "999")
		}.andExpect {
			status { isOk() }
			jsonPath("$.data.size", equalTo(50))
		}
	}

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun savePost(
		author: User,
		tags: Set<String> = emptySet(),
		title: String = "상세 조회 테스트",
		categoryCode: String = "TRAVEL_REVIEW",
	): CommunityPost {
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue(categoryCode)!!
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
		post.assignTags(tags.map { name -> communityTagRepository.findByName(name) ?: saveTag(name) }.toSet())
		return communityPostRepository.saveAndFlush(post)
	}

	private fun setCreatedAt(
		postId: UUID,
		createdAt: Instant,
	) {
		jdbcTemplate.update("UPDATE community_post SET created_at = ? WHERE id = ?", Timestamp.from(createdAt), postId)
		entityManager.clear()
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
