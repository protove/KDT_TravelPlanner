package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommentCreateRequest
import com.ktcloud.travelplanner.community.model.CommunityComment
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.repository.CommunityCommentRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
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

	@Test
	fun `getComments returns comments ordered by createdAt and marks the requester's own comment as isMine`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		val ownerId = UUID.randomUUID()
		val ownComment = mockComment(commentAuthorId = ownerId, content = "첫 댓글")
		val otherComment = mockComment(commentAuthorId = UUID.randomUUID(), content = "둘째 댓글")
		`when`(communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId))
			.thenReturn(listOf(ownComment, otherComment))

		val response = service.getComments(postId, ownerId)

		assertEquals(2, response.size)
		assertEquals("첫 댓글", response[0].content)
		assertTrue(response[0].isMine)
		assertFalse(response[1].isMine)
	}

	@Test
	fun `getComments returns isMine false for every comment when the requester is anonymous`() {
		`when`(communityPostRepository.findById(postId)).thenReturn(Optional.of(mock(CommunityPost::class.java)))
		`when`(communityCommentRepository.findAllByPostIdOrderByCreatedAtAsc(postId))
			.thenReturn(listOf(mockComment(commentAuthorId = UUID.randomUUID())))

		val response = service.getComments(postId, null)

		assertFalse(response[0].isMine)
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
	fun `createComment saves a comment linked to the post and author, returning isMine true`() {
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
	fun `deleteComment soft deletes when the requester is the author`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId)
		`when`(communityCommentRepository.findById(commentId)).thenReturn(Optional.of(comment))

		service.deleteComment(commentId, authorId)

		verify(comment).softDelete(any(Instant::class.java))
	}

	@Test
	fun `deleteComment throws access denied for a non-author requester without deleting`() {
		val commentId = UUID.randomUUID()
		val authorId = UUID.randomUUID()
		val comment = mockComment(commentAuthorId = authorId)
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

	private fun mockComment(
		commentAuthorId: UUID,
		content: String = "댓글",
	): CommunityComment {
		val commentAuthor = mock(User::class.java)
		`when`(commentAuthor.id).thenReturn(commentAuthorId)
		`when`(commentAuthor.nickname).thenReturn("작성자")
		`when`(commentAuthor.profileImageUrl).thenReturn(null)

		val comment = mock(CommunityComment::class.java)
		`when`(comment.id).thenReturn(UUID.randomUUID())
		`when`(comment.author).thenReturn(commentAuthor)
		`when`(comment.content).thenReturn(content)
		`when`(comment.createdAt).thenReturn(Instant.parse("2026-08-01T00:00:00Z"))
		return comment
	}
}
