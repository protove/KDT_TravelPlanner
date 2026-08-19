package com.ktcloud.travelplanner.community.service

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.model.CommunityCategory
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.community.validation.InvalidBodyJsonException
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.ArgumentMatchers.anyString
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.times
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CommunityPostServiceTest {
	private val communityCategoryRepository = mock(CommunityCategoryRepository::class.java)
	private val communityTagRepository = mock(CommunityTagRepository::class.java)
	private val communityPostRepository = mock(CommunityPostRepository::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val service = CommunityPostService(
		communityCategoryRepository,
		communityTagRepository,
		communityPostRepository,
		userRepository,
		travelRepository,
		travelMemberRepository,
	)
	private val objectMapper = ObjectMapper()

	private val authorId = UUID.randomUUID()
	private val author = User(OAuthProvider.GOOGLE, "community-author")
	private val category = CommunityCategory(id = 1, code = "TRAVEL_REVIEW", name = "여행후기", sortOrder = 1, isActive = true)

	@Test
	fun `creates a post under the travel review category and returns the generated id`() {
		stubAuthorAndCategory()
		var savedPost: CommunityPost? = null
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0).also { post -> savedPost = post } }

		val response = service.createPost(authorId, request())

		assertEquals(savedPost!!.id, response.postId)
		assertEquals("제주도 여행 후기", savedPost!!.title)
		assertTrue(savedPost!!.tags.isEmpty())
		assertNull(savedPost!!.sourceTravelId)
	}

	@Test
	fun `computes bodyPreview from text nodes joined with a space and truncated at 120 chars`() {
		stubAuthorAndCategory()
		var savedPost: CommunityPost? = null
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0).also { post -> savedPost = post } }
		val longText = "가".repeat(130)
		val body = tiptapDoc("첫문단", longText)

		service.createPost(authorId, request(bodyJson = body))

		val expected = "첫문단 $longText".take(120) + "…"
		assertEquals(expected, savedPost!!.bodyPreview)
	}

	@Test
	fun `rejects categories other than TRAVEL_REVIEW before touching other repositories`() {
		assertThrows<UnsupportedCommunityCategoryException> {
			service.createPost(authorId, request(categoryCode = "FREE"))
		}

		verifyNoInteractions(communityCategoryRepository, userRepository, communityPostRepository)
	}

	@Test
	fun `rejects bodyJson outside the tiptap whitelist without persisting`() {
		stubAuthorAndCategory()
		val invalidBody = objectMapper.readTree("""{"type":"codeBlock"}""")

		assertThrows<InvalidBodyJsonException> {
			service.createPost(authorId, request(bodyJson = invalidBody))
		}

		verifyNoInteractions(communityPostRepository)
	}

	@Test
	fun `finds an existing tag by name and creates a missing one via insert-or-ignore`() {
		stubAuthorAndCategory()
		val existingTag = CommunityTag(name = "부산")
		`when`(communityTagRepository.findByName("부산")).thenReturn(existingTag)
		`when`(communityTagRepository.findByName("신규태그"))
			.thenReturn(null)
			.thenReturn(CommunityTag(name = "신규태그"))
		var savedPost: CommunityPost? = null
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0).also { post -> savedPost = post } }

		service.createPost(authorId, request(tags = listOf("부산", "신규태그")))

		verify(communityTagRepository).insertIgnoringConflict("신규태그")
		verify(communityTagRepository, never()).insertIgnoringConflict("부산")
		assertEquals(setOf("부산", "신규태그"), savedPost!!.tags.map { it.name }.toSet())
	}

	@Test
	fun `trims tag names and deduplicates before validating count`() {
		stubAuthorAndCategory()
		`when`(communityTagRepository.findByName(anyString())).thenReturn(CommunityTag(name = "제주"))
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0) }

		service.createPost(authorId, request(tags = listOf(" 제주 ", "제주")))

		verify(communityTagRepository, times(1)).findByName("제주")
	}

	@Test
	fun `rejects more than 5 distinct tags`() {
		stubAuthorAndCategory()

		assertThrows<TooManyCommunityTagsException> {
			service.createPost(authorId, request(tags = listOf("a", "b", "c", "d", "e", "f")))
		}

		verifyNoInteractions(communityTagRepository)
	}

	@Test
	fun `rejects a tag name that is blank after trim or longer than 20 chars`() {
		stubAuthorAndCategory()

		assertThrows<InvalidCommunityTagNameException> {
			service.createPost(authorId, request(tags = listOf("   ")))
		}
		assertThrows<InvalidCommunityTagNameException> {
			service.createPost(authorId, request(tags = listOf("가".repeat(21))))
		}
	}

	@Test
	fun `allows the travel owner to attach sourceTravelId without a member lookup`() {
		stubAuthorAndCategory()
		val travelId = UUID.randomUUID()
		val travel = travelOwnedBy(authorId)
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0) }

		service.createPost(authorId, request(sourceTravelId = travelId))

		verify(travelMemberRepository, never()).findAcceptedRole(travelId, authorId)
	}

	@Test
	fun `allows an accepted member to attach sourceTravelId`() {
		stubAuthorAndCategory()
		val travelId = UUID.randomUUID()
		val travel = travelOwnedBy(UUID.randomUUID())
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(travelId, authorId)).thenReturn(TravelRole.READ_ONLY)
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0) }

		service.createPost(authorId, request(sourceTravelId = travelId))
	}

	@Test
	fun `rejects sourceTravelId when the requester has no accepted access`() {
		stubAuthorAndCategory()
		val travelId = UUID.randomUUID()
		val travel = travelOwnedBy(UUID.randomUUID())
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(travelId, authorId)).thenReturn(null)

		assertThrows<CommunityPostSourceTravelAccessDeniedException> {
			service.createPost(authorId, request(sourceTravelId = travelId))
		}

		verifyNoInteractions(communityPostRepository)
	}

	@Test
	fun `rejects a sourceTravelId that does not exist`() {
		stubAuthorAndCategory()
		val travelId = UUID.randomUUID()
		`when`(travelRepository.findById(travelId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostSourceTravelNotFoundException> {
			service.createPost(authorId, request(sourceTravelId = travelId))
		}
	}

	@Test
	fun `rejects an unknown author`() {
		`when`(communityCategoryRepository.findByCodeAndIsActiveTrue("TRAVEL_REVIEW")).thenReturn(category)
		`when`(userRepository.findById(authorId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostAuthorNotFoundException> {
			service.createPost(authorId, request())
		}

		verifyNoInteractions(communityPostRepository)
	}

	private fun stubAuthorAndCategory() {
		`when`(communityCategoryRepository.findByCodeAndIsActiveTrue("TRAVEL_REVIEW")).thenReturn(category)
		`when`(userRepository.findById(authorId)).thenReturn(Optional.of(author))
	}

	private fun travelOwnedBy(ownerId: UUID): Travel {
		val owner = mock(User::class.java)
		`when`(owner.id).thenReturn(ownerId)
		val travel = mock(Travel::class.java)
		`when`(travel.owner).thenReturn(owner)
		return travel
	}

	private fun tiptapDoc(vararg paragraphs: String): JsonNode {
		val content = paragraphs.joinToString(",") { text ->
			"""{"type":"paragraph","content":[{"type":"text","text":${objectMapper.writeValueAsString(text)}}]}"""
		}
		return objectMapper.readTree("""{"type":"doc","content":[$content]}""")
	}

	private fun request(
		categoryCode: String = "TRAVEL_REVIEW",
		bodyJson: JsonNode = tiptapDoc("안녕하세요"),
		tags: List<String>? = null,
		sourceTravelId: UUID? = null,
	): CommunityPostCreateRequest = CommunityPostCreateRequest(
		categoryCode = categoryCode,
		title = "제주도 여행 후기",
		bodyJson = bodyJson,
		tags = tags,
		sourceTravelId = sourceTravelId,
	)
}
