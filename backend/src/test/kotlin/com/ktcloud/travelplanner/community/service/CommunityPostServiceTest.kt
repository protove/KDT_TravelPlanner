package com.ktcloud.travelplanner.community.service

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostUpdateRequest
import com.ktcloud.travelplanner.community.model.CommunityCategory
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostListRow
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostTagNameRow
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.community.validation.InvalidBodyJsonException
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.dto.PatchField
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
import org.springframework.data.domain.PageImpl
import org.springframework.data.domain.PageRequest
import java.time.Instant
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CommunityPostServiceTest {
	private val communityCategoryRepository = mock(CommunityCategoryRepository::class.java)
	private val communityTagRepository = mock(CommunityTagRepository::class.java)
	private val communityPostRepository = mock(CommunityPostRepository::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val objectMapper = ObjectMapper()
	private val service = CommunityPostService(
		communityCategoryRepository,
		communityTagRepository,
		communityPostRepository,
		userRepository,
		travelRepository,
		travelMemberRepository,
		objectMapper,
	)

	private val authorId = UUID.randomUUID()
	private val author = User(OAuthProvider.GOOGLE, "community-author")
	private val category = CommunityCategory(id = 1, code = "TRAVEL_REVIEW", name = "여행후기", sortOrder = 1, isActive = true)

	// ArgumentMatchers.any(Class)는 자바 선언이라 런타임에 null을 반환한다. CommunityPost.softDelete
	// (deletedAt: Instant)처럼 코틀린 non-null 파라미터 자리에 그대로 넘기면, 코틀린 컴파일러가
	// 호출부에 넣어주는 null 체크(Intrinsics.checkNotNullParameter)에 걸려 NPE가 즉시 터진다
	// (CommunityCommentServiceTest와 동일한 문제) — 그림자 함수로 감싸서 우회한다.
	private fun <T> any(type: Class<T>): T {
		org.mockito.ArgumentMatchers.any(type)
		@Suppress("UNCHECKED_CAST")
		return null as T
	}

	// assignTags(tags: Set<CommunityTag>)처럼 non-null 파라미터를 받는 코틀린 선언 자리에
	// 타입 없는 any()를 그대로 넘길 때 쓰는 그림자 함수(위 any(Class<T>)와 동일한 이유).
	private fun <T> any(): T {
		org.mockito.ArgumentMatchers.any<T>()
		@Suppress("UNCHECKED_CAST")
		return null as T
	}

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
	fun `rejects the NOTICE category before touching other repositories`() {
		assertThrows<UnsupportedCommunityCategoryException> {
			service.createPost(authorId, request(categoryCode = "NOTICE"))
		}

		verifyNoInteractions(communityCategoryRepository, userRepository, communityPostRepository)
	}

	@Test
	fun `creates a post under any active non-NOTICE category`() {
		val freeCategory = CommunityCategory(id = 2, code = "FREE", name = "자유게시판", sortOrder = 2, isActive = true)
		`when`(communityCategoryRepository.findByCodeAndIsActiveTrue("FREE")).thenReturn(freeCategory)
		`when`(userRepository.findById(authorId)).thenReturn(Optional.of(author))
		`when`(communityPostRepository.save(any(CommunityPost::class.java)))
			.thenAnswer { it.getArgument<CommunityPost>(0) }

		service.createPost(authorId, request(categoryCode = "FREE"))
	}

	@Test
	fun `rejects a category code that does not exist or is inactive`() {
		`when`(communityCategoryRepository.findByCodeAndIsActiveTrue("QNA")).thenReturn(null)

		assertThrows<CommunityCategoryNotFoundException> {
			service.createPost(authorId, request(categoryCode = "QNA"))
		}

		verifyNoInteractions(userRepository, communityPostRepository)
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

	@Test
	fun `updatePost edits title and bodyJson for the author and returns fresh detail`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 0)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(communityPostRepository.saveAndFlush(post)).thenReturn(post)
		`when`(communityPostRepository.countActiveComments(postId)).thenReturn(2L)
		`when`(communityPostRepository.countReactions(postId)).thenReturn(5L)
		val newBody = tiptapDoc("수정된 내용")

		val response = service.updatePost(
			postId,
			authorId,
			CommunityPostUpdateRequest(
				title = PatchField.Present("새 제목"),
				bodyJson = PatchField.Present(newBody),
				version = 0,
			),
		)

		verify(post).edit(title = "새 제목", bodyJson = newBody.toString(), bodyPreview = "수정된 내용")
		verify(post, never()).assignTags(any())
		assertTrue(response.isMine)
		assertEquals(2L, response.commentCount)
		assertEquals(5L, response.reactionCount)
	}

	@Test
	fun `updatePost replaces tags when tags field is present`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 0)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(communityPostRepository.saveAndFlush(post)).thenReturn(post)
		// CommunityTag는 equals/hashCode를 오버라이드하지 않아 참조 동일성으로 비교되므로,
		// 스텁이 반환하는 것과 같은 인스턴스를 검증에도 그대로 재사용한다.
		val jejuTag = CommunityTag(name = "제주")
		`when`(communityTagRepository.findByName(anyString())).thenReturn(jejuTag)

		service.updatePost(postId, authorId, CommunityPostUpdateRequest(tags = PatchField.Present(listOf("제주")), version = 0))

		verify(post).assignTags(setOf(jejuTag))
	}

	@Test
	fun `updatePost throws access denied for a non-author requester without editing`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 0)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		assertThrows<CommunityPostAccessDeniedException> {
			service.updatePost(postId, UUID.randomUUID(), CommunityPostUpdateRequest(title = PatchField.Present("새 제목"), version = 0))
		}
		verify(post, never()).edit(any(), any(), any())
	}

	@Test
	fun `updatePost throws version conflict when the requested version does not match`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 3)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		assertThrows<CommunityPostVersionConflictException> {
			service.updatePost(postId, authorId, CommunityPostUpdateRequest(title = PatchField.Present("새 제목"), version = 0))
		}
		verify(post, never()).edit(any(), any(), any())
	}

	@Test
	fun `updatePost throws when the new title is blank`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 0)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		assertThrows<InvalidCommunityPostUpdateException> {
			service.updatePost(postId, authorId, CommunityPostUpdateRequest(title = PatchField.Present("   "), version = 0))
		}
	}

	@Test
	fun `updatePost throws when the new bodyJson violates the tiptap whitelist`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId, version = 0)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		val invalidBody = objectMapper.readTree("""{"type":"codeBlock"}""")

		assertThrows<InvalidBodyJsonException> {
			service.updatePost(postId, authorId, CommunityPostUpdateRequest(bodyJson = PatchField.Present(invalidBody), version = 0))
		}
	}

	@Test
	fun `updatePost throws when the post does not exist or is soft deleted`() {
		val postId = UUID.randomUUID()
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.updatePost(postId, authorId, CommunityPostUpdateRequest(title = PatchField.Present("새 제목"), version = 0))
		}
	}

	@Test
	fun `deletePost soft deletes when the requester is the author`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		service.deletePost(postId, authorId)

		verify(post).softDelete(any(Instant::class.java))
	}

	@Test
	fun `deletePost throws access denied for a non-author requester without deleting`() {
		val postId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = authorId)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		assertThrows<CommunityPostAccessDeniedException> {
			service.deletePost(postId, UUID.randomUUID())
		}
		verify(post, never()).softDelete(any(Instant::class.java))
	}

	@Test
	fun `toggleReaction inserts a like when the requester has not reacted yet`() {
		val postId = UUID.randomUUID()
		val requesterId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = UUID.randomUUID())
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(communityPostRepository.existsReaction(postId, requesterId)).thenReturn(false)
		`when`(communityPostRepository.countReactions(postId)).thenReturn(1L)

		val response = service.toggleReaction(postId, requesterId, "LIKE")

		verify(communityPostRepository).insertReaction(postId, requesterId)
		verify(communityPostRepository, never()).deleteReaction(postId, requesterId)
		assertTrue(response.isReacted)
		assertEquals(1L, response.reactionCount)
	}

	@Test
	fun `toggleReaction removes the like when the requester already reacted`() {
		val postId = UUID.randomUUID()
		val requesterId = UUID.randomUUID()
		val post = mockCommunityPost(postAuthorId = UUID.randomUUID())
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(communityPostRepository.existsReaction(postId, requesterId)).thenReturn(true)
		`when`(communityPostRepository.countReactions(postId)).thenReturn(0L)

		val response = service.toggleReaction(postId, requesterId, "LIKE")

		verify(communityPostRepository).deleteReaction(postId, requesterId)
		verify(communityPostRepository, never()).insertReaction(postId, requesterId)
		assertFalse(response.isReacted)
	}

	@Test
	fun `toggleReaction rejects a type other than LIKE without touching the repository`() {
		assertThrows<UnsupportedCommunityReactionTypeException> {
			service.toggleReaction(UUID.randomUUID(), UUID.randomUUID(), "DISLIKE")
		}
		verifyNoInteractions(communityPostRepository)
	}

	@Test
	fun `toggleReaction throws when the post does not exist or is soft deleted`() {
		val postId = UUID.randomUUID()
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.toggleReaction(postId, UUID.randomUUID(), "LIKE")
		}
	}

	@Test
	fun `deletePost throws when the post does not exist or is soft deleted`() {
		val postId = UUID.randomUUID()
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.deletePost(postId, UUID.randomUUID())
		}
	}

	@Test
	fun `getPostDetail increments the view count and returns comment and reaction counts`() {
		val postId = UUID.randomUUID()
		val post = mockPost(postId, postAuthorId = authorId, viewCount = 5)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(communityPostRepository.countActiveComments(postId)).thenReturn(2L)
		`when`(communityPostRepository.countReactions(postId)).thenReturn(3L)

		val response = service.getPostDetail(postId, authorId)

		verify(communityPostRepository).incrementViewCount(postId)
		assertEquals(6, response.viewCount)
		assertEquals(2L, response.commentCount)
		assertEquals(3L, response.reactionCount)
		assertTrue(response.isMine)
	}

	@Test
	fun `getPostDetail marks isMine false for a different or anonymous requester`() {
		val postId = UUID.randomUUID()
		val post = mockPost(postId, postAuthorId = authorId)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))

		assertFalse(service.getPostDetail(postId, UUID.randomUUID()).isMine)
		assertFalse(service.getPostDetail(postId, null).isMine)
	}

	@Test
	fun `getPosts returns createdAt-sorted results by default and attaches tags per post`() {
		val postId1 = UUID.randomUUID()
		val postId2 = UUID.randomUUID()
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, null, "ALL", pageable))
			.thenReturn(PageImpl(listOf(listRow(postId1), listRow(postId2)), pageable, 2))
		`when`(communityPostRepository.findTagNamesByPostIds(listOf(postId1, postId2)))
			.thenReturn(
				listOf(
					CommunityPostTagNameRow(postId1, "부산"),
					CommunityPostTagNameRow(postId1, "맛집"),
				),
			)

		val response = service.getPosts(null, null, null, null, null, 0, 10)

		assertEquals(listOf("부산", "맛집"), response.content[0].tags)
		assertEquals(emptyList(), response.content[1].tags)
		assertEquals(0L, response.content[0].reactionCount)
		assertEquals(0L, response.content[0].commentCount)
		verify(communityPostRepository, never()).findPostsOrderByPopularity(null, null, null, "ALL", pageable)
	}

	@Test
	fun `getPosts orders by popularity when sort is popular`() {
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByPopularity(null, null, null, "ALL", pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getPosts(null, null, null, null, "popular", 0, 10)

		verify(communityPostRepository).findPostsOrderByPopularity(null, null, null, "ALL", pageable)
		verify(communityPostRepository, never()).findPostsOrderByCreatedAt(null, null, null, "ALL", pageable)
	}

	@Test
	fun `getPosts clamps size to the 1 to 50 range`() {
		val minPageable = PageRequest.of(0, 1)
		val maxPageable = PageRequest.of(0, 50)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, null, "ALL", minPageable))
			.thenReturn(PageImpl(emptyList(), minPageable, 0))
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, null, "ALL", maxPageable))
			.thenReturn(PageImpl(emptyList(), maxPageable, 0))

		service.getPosts(null, null, null, null, null, 0, 0)
		service.getPosts(null, null, null, null, null, 0, 999)

		verify(communityPostRepository).findPostsOrderByCreatedAt(null, null, null, "ALL", minPageable)
		verify(communityPostRepository).findPostsOrderByCreatedAt(null, null, null, "ALL", maxPageable)
	}

	@Test
	fun `getPosts trims blank filters down to null before querying`() {
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, null, "ALL", pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getPosts("  ", "", "   ", null, null, 0, 10)

		verify(communityPostRepository).findPostsOrderByCreatedAt(null, null, null, "ALL", pageable)
	}

	@Test
	fun `getPosts skips the tag lookup when there are no results`() {
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, null, "ALL", pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getPosts(null, null, null, null, null, 0, 10)

		verify(communityPostRepository, never()).findTagNamesByPostIds(emptyList())
	}

	@Test
	fun `getPosts uppercases a valid searchScope before querying`() {
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, "부산", "AUTHOR", pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getPosts(null, null, "부산", "author", null, 0, 10)

		verify(communityPostRepository).findPostsOrderByCreatedAt(null, null, "부산", "AUTHOR", pageable)
	}

	@Test
	fun `getPosts falls back to ALL for a searchScope outside the whitelist`() {
		val pageable = PageRequest.of(0, 10)
		`when`(communityPostRepository.findPostsOrderByCreatedAt(null, null, "부산", "ALL", pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getPosts(null, null, "부산", "unknown-scope", null, 0, 10)

		verify(communityPostRepository).findPostsOrderByCreatedAt(null, null, "부산", "ALL", pageable)
	}

	private fun listRow(
		postId: UUID,
		createdAt: Instant = Instant.parse("2026-08-01T00:00:00Z"),
	): CommunityPostListRow = CommunityPostListRow(
		postId = postId,
		categoryCode = "TRAVEL_REVIEW",
		title = "목록 테스트",
		bodyPreview = "미리보기",
		authorNickname = "작성자",
		authorProfileImageUrl = null,
		viewCount = 0,
		sourceTravelId = null,
		createdAt = createdAt,
	)

	@Test
	fun `getPostDetail throws when the post does not exist or is soft deleted`() {
		val postId = UUID.randomUUID()
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.getPostDetail(postId, null)
		}
		verify(communityPostRepository, never()).incrementViewCount(postId)
	}

	private fun mockPost(
		postId: UUID,
		postAuthorId: UUID,
		viewCount: Int = 5,
	): CommunityPost {
		val postAuthor = mock(User::class.java)
		`when`(postAuthor.id).thenReturn(postAuthorId)
		`when`(postAuthor.nickname).thenReturn("작성자")
		`when`(postAuthor.profileImageUrl).thenReturn(null)

		val post = mock(CommunityPost::class.java)
		`when`(post.id).thenReturn(postId)
		`when`(post.author).thenReturn(postAuthor)
		`when`(post.category).thenReturn(category)
		`when`(post.title).thenReturn("상세 테스트")
		`when`(post.bodyPreview).thenReturn("미리보기")
		`when`(post.bodyJson).thenReturn("""{"type":"doc"}""")
		`when`(post.tags).thenReturn(mutableSetOf())
		`when`(post.sourceTravelId).thenReturn(null)
		`when`(post.viewCount).thenReturn(viewCount)
		`when`(post.createdAt).thenReturn(Instant.parse("2026-08-01T00:00:00Z"))
		return post
	}

	// updatePost/deletePost 테스트 전용 — version과 saveAndFlush 이후 재조립에 필요한 필드들을 채운다.
	private fun mockCommunityPost(
		postAuthorId: UUID,
		version: Int = 0,
	): CommunityPost {
		val postAuthor = mock(User::class.java)
		`when`(postAuthor.id).thenReturn(postAuthorId)

		val post = mock(CommunityPost::class.java)
		`when`(post.id).thenReturn(UUID.randomUUID())
		`when`(post.author).thenReturn(postAuthor)
		`when`(post.category).thenReturn(category)
		`when`(post.version).thenReturn(version)
		`when`(post.title).thenReturn("기존 제목")
		`when`(post.bodyJson).thenReturn("""{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"기존 내용"}]}]}""")
		`when`(post.viewCount).thenReturn(3)
		`when`(post.createdAt).thenReturn(Instant.parse("2026-08-01T00:00:00Z"))
		return post
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
