package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommentCreateRequest
import com.ktcloud.travelplanner.community.model.CommunityComment
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.repository.CommentReactionCountRow
import com.ktcloud.travelplanner.community.repository.CommunityCommentRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.Instant
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CommunityCommentServiceTest {
	private val communityPostRepository = mock(CommunityPostRepository::class.java)
	private val communityCommentRepository = mock(CommunityCommentRepository::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val service = CommunityCommentService(
		communityPostRepository,
		communityCommentRepository,
		userRepository,
	)

	private val postId = UUID.randomUUID()

	// org.mockito.ArgumentMatchers.any()/any(Class<T>)는 자바로 선언되어 있어서 런타임에 null을
	// 반환한다. 이 결과를 코틀린으로 선언된 non-null 파라미터(예: CommunityComment.edit(content:
	// String, ...), CommunityCommentRepository.countReactionsByCommentIds(commentIds: List<UUID>))
	// 자리에 그대로 넘기면, 코틀린 컴파일러가 "호출 지점에" 넣어주는 Intrinsics.checkNotNullExpressionValue
	// null 체크에 걸려 "any(...) must not be null" NPE가 즉시 터진다 — 스터빙/검증 로직과는 무관한,
	// 순수 코틀린-자바 상호운용 문제다. 그래서 실제 ArgumentMatchers.any(...)를 호출해 매처 등록은
	// 그대로 해주되, 코틀린으로 선언된 non-null 타입 T를 반환하는 얇은 래퍼로 감싸서 아래에서 그림자
	// 함수(shadowing)로 대체한다 — 아래 테스트 본문의 `any()`, `any(Instant::class.java)` 같은
	// 호출부는 전혀 손대지 않아도 된다(멤버 함수가 import된 top-level 함수보다 우선 해석된다).
	private fun <T> any(): T {
		ArgumentMatchers.any<T>()
		@Suppress("UNCHECKED_CAST")
		return null as T
	}

	private fun <T> any(type: Class<T>): T {
		ArgumentMatchers.any(type)
		@Suppress("UNCHECKED_CAST")
		return null as T
	}

	// eq(value)는 실제 값을 인자로 받으므로 언뜻 안전해 보이지만, 내부적으로 Mockito(자바)가
	// 그 값을 그대로 돌려주지 않고 타입별 기본값(참조 타입은 null)을 반환하도록 구현되어 있어서
	// any()와 완전히 동일한 문제(호출 지점 null 체크로 인한 "eq(...) must not be null" NPE)가
	// 생긴다 — 처음엔 "실제 값을 넘기니 안전하다"고 잘못 판단했던 부분. 여기서는 애초에 넘겨받은
	// 실제 값 자체를 그대로 반환하므로, null 관련 문제 자체가 생기지 않는다.
	private fun <T> eq(value: T): T {
		ArgumentMatchers.eq(value)
		return value
	}

	@Test
	fun `getComments returns comments ordered by createdAt with reaction counts and isMine per requester`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		val ownerId = UUID.randomUUID()
		val ownComment = mockComment(commentAuthorId = ownerId, content = "첫 댓글")
		val otherComment = mockComment(commentAuthorId = UUID.randomUUID(), content = "둘째 댓글")
		val commentIds = listOf(ownComment.id, otherComment.id)
		// reactionCountRow(...)와 아래 reactedIds 둘 다, 다른 when(...).thenReturn(...)의 인자 자리에서
		// 모킹된 프로퍼티(ownComment.id, otherComment.id 등)를 바로 호출하면 안 된다 — Mockito가 아직
		// 완료되지 않은 바깥쪽 스터빙(OngoingStubbing) 도중에 안쪽 모킹 호출이 끼어드는 걸로 인식해서
		// 상태가 꼬이고, 그 여파로 이후 테스트들에서까지 엉뚱한 UnfinishedStubbingException /
		// InvalidUseOfMatchersException이 터진다. 그래서 먼저 로컬 변수로 완전히 평가/확정해둔 뒤에 쓴다.
		val reactionCountRows = listOf(reactionCountRow(ownComment.id, 3L))
		val reactedIds = listOf(otherComment.id)
		`when`(communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId))
			.thenReturn(listOf(ownComment, otherComment))
		`when`(communityCommentRepository.countReactionsByCommentIds(commentIds))
			.thenReturn(reactionCountRows)
		`when`(communityCommentRepository.findReactedCommentIds(commentIds, ownerId))
			.thenReturn(reactedIds)

		val response = service.getComments(postId, ownerId)

		assertEquals(2, response.size)
		assertEquals("첫 댓글", response[0].content)
		assertTrue(response[0].isMine)
		assertEquals(3L, response[0].reactionCount)
		assertFalse(response[0].isReacted)
		assertFalse(response[1].isMine)
		assertEquals(0L, response[1].reactionCount)
		assertTrue(response[1].isReacted)
	}

	@Test
	fun `getComments skips the reaction batch lookup when there are no comments`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		`when`(communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId)).thenReturn(emptyList())

		val response = service.getComments(postId, UUID.randomUUID())

		assertTrue(response.isEmpty())
		verify(communityCommentRepository, never()).countReactionsByCommentIds(any())
	}

	@Test
	fun `getComments does not look up reacted ids for an anonymous requester`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		val comment = mockComment(commentAuthorId = UUID.randomUUID())
		`when`(communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId)).thenReturn(listOf(comment))
		`when`(communityCommentRepository.countReactionsByCommentIds(listOf(comment.id))).thenReturn(emptyList())

		val response = service.getComments(postId, null)

		assertFalse(response[0].isMine)
		assertFalse(response[0].isReacted)
		verify(communityCommentRepository, never()).findReactedCommentIds(any(), any())
	}

	@Test
	fun `getComments throws when the post does not exist or is soft deleted`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.getComments(postId, null)
		}
		verifyNoInteractions(communityCommentRepository)
	}

	@Test
	fun `createComment saves a comment with zero reactions, returning isMine true`() {
		val authorId = UUID.randomUUID()
		val post = mock(CommunityPost::class.java)
		val author = mock(User::class.java)
		`when`(author.id).thenReturn(authorId)
		`when`(author.nickname).thenReturn("작성자")
		`when`(author.profileImageUrl).thenReturn(null)
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(post))
		`when`(userRepository.findById(authorId)).thenReturn(Optional.of(author))
		var savedComment: CommunityComment? = null
		`when`(communityCommentRepository.save(any(CommunityComment::class.java)))
			.thenAnswer { it.getArgument<CommunityComment>(0).also { comment -> savedComment = comment } }

		val response = service.createComment(postId, authorId, CommentCreateRequest("좋은 글이네요"))

		assertEquals(post, savedComment!!.post)
		assertEquals(author, savedComment!!.author)
		assertEquals("좋은 글이네요", savedComment!!.content)
		assertEquals("좋은 글이네요", response.content)
		assertTrue(response.isMine)
		assertEquals(0L, response.reactionCount)
		assertFalse(response.isReacted)
	}

	@Test
	fun `createComment throws when the post does not exist, without touching the author or comment repository`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.empty())

		assertThrows<CommunityPostNotFoundException> {
			service.createComment(postId, UUID.randomUUID(), CommentCreateRequest("댓글"))
		}
		verifyNoInteractions(userRepository, communityCommentRepository)
	}

	@Test
	fun `createComment throws when the author does not exist`() {
		val authorId = UUID.randomUUID()
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		`when`(userRepository.findById(authorId)).thenReturn(Optional.empty())

		assertThrows<CommunityCommentAuthorNotFoundException> {
			service.createComment(postId, authorId, CommentCreateRequest("댓글"))
		}
		verifyNoInteractions(communityCommentRepository)
	}

	@Test
	fun `updateComment edits content when the requester is the author`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId, commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))
		`when`(communityCommentRepository.countReactions(commentId)).thenReturn(2L)
		`when`(communityCommentRepository.existsReaction(commentId, authorId)).thenReturn(true)

		val response = service.updateComment(commentId, authorId, CommentCreateRequest("고친 내용"))

		verify(comment).edit(eq("고친 내용"), any(Instant::class.java))
		assertTrue(response.isMine)
		assertEquals(2L, response.reactionCount)
		assertTrue(response.isReacted)
	}

	@Test
	fun `updateComment throws access denied for a non-author requester without editing`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId, commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))

		assertThrows<CommunityCommentAccessDeniedException> {
			service.updateComment(commentId, UUID.randomUUID(), CommentCreateRequest("고친 내용"))
		}
		verify(comment, never()).edit(any(), any())
	}

	@Test
	fun `updateComment throws when the comment does not exist or is soft deleted`() {
		val commentId = UUID.randomUUID()
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.empty())

		assertThrows<CommunityCommentNotFoundException> {
			service.updateComment(commentId, UUID.randomUUID(), CommentCreateRequest("고친 내용"))
		}
	}

	@Test
	fun `deleteComment soft deletes when the requester is the author`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId, commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))

		service.deleteComment(commentId, authorId)

		verify(comment).softDelete(any(Instant::class.java))
	}

	@Test
	fun `deleteComment throws access denied for a non-author requester without deleting`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId, commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))

		assertThrows<CommunityCommentAccessDeniedException> {
			service.deleteComment(commentId, UUID.randomUUID())
		}
		verify(comment, never()).softDelete(any(Instant::class.java))
	}

	@Test
	fun `deleteComment throws when the comment does not exist or is soft deleted`() {
		val commentId = UUID.randomUUID()
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.empty())

		assertThrows<CommunityCommentNotFoundException> {
			service.deleteComment(commentId, UUID.randomUUID())
		}
	}

	@Test
	fun `toggleReaction inserts a like when the requester has not reacted yet`() {
		val commentId = UUID.randomUUID()
		val requesterId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = UUID.randomUUID(), commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))
		`when`(communityCommentRepository.existsReaction(commentId, requesterId)).thenReturn(false)
		`when`(communityCommentRepository.countReactions(commentId)).thenReturn(1L)

		val response = service.toggleReaction(commentId, requesterId, "LIKE")

		verify(communityCommentRepository).insertReaction(commentId, requesterId)
		verify(communityCommentRepository, never()).deleteReaction(commentId, requesterId)
		assertTrue(response.isReacted)
		assertEquals(1L, response.reactionCount)
	}

	@Test
	fun `toggleReaction removes the like when the requester already reacted`() {
		val commentId = UUID.randomUUID()
		val requesterId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = UUID.randomUUID(), commentId = commentId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))
		`when`(communityCommentRepository.existsReaction(commentId, requesterId)).thenReturn(true)
		`when`(communityCommentRepository.countReactions(commentId)).thenReturn(0L)

		val response = service.toggleReaction(commentId, requesterId, "LIKE")

		verify(communityCommentRepository).deleteReaction(commentId, requesterId)
		verify(communityCommentRepository, never()).insertReaction(commentId, requesterId)
		assertFalse(response.isReacted)
	}

	@Test
	fun `toggleReaction rejects a type other than LIKE without touching the repository`() {
		assertThrows<UnsupportedCommentReactionTypeException> {
			service.toggleReaction(UUID.randomUUID(), UUID.randomUUID(), "DISLIKE")
		}
		verifyNoInteractions(communityCommentRepository)
	}

	@Test
	fun `toggleReaction throws when the comment does not exist or is soft deleted`() {
		val commentId = UUID.randomUUID()
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.empty())

		assertThrows<CommunityCommentNotFoundException> {
			service.toggleReaction(commentId, UUID.randomUUID(), "LIKE")
		}
	}

	private fun reactionCountRow(
		commentId: UUID,
		count: Long,
	): CommentReactionCountRow {
		val row = mock(CommentReactionCountRow::class.java)
		`when`(row.commentId).thenReturn(commentId)
		`when`(row.reactionCount).thenReturn(count)
		return row
	}

	private fun mockComment(
		commentAuthorId: UUID,
		commentId: UUID = UUID.randomUUID(),
		content: String = "댓글",
	): CommunityComment {
		val commentAuthor = mock(User::class.java)
		`when`(commentAuthor.id).thenReturn(commentAuthorId)
		`when`(commentAuthor.nickname).thenReturn("작성자")
		`when`(commentAuthor.profileImageUrl).thenReturn(null)

		val comment = mock(CommunityComment::class.java)
		`when`(comment.id).thenReturn(commentId)
		`when`(comment.author).thenReturn(commentAuthor)
		`when`(comment.content).thenReturn(content)
		`when`(comment.createdAt).thenReturn(Instant.parse("2026-08-01T00:00:00Z"))
		`when`(comment.updatedAt).thenReturn(null)
		return comment
	}
}
