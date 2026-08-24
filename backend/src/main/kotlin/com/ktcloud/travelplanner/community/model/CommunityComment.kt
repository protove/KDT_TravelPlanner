package com.ktcloud.travelplanner.community.model

import com.ktcloud.travelplanner.user.model.User
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import org.hibernate.annotations.SQLRestriction
import java.time.Instant
import java.util.UUID

// community_comment는 수정 없이 작성/소프트삭제만 지원한다 (V17 — updated_at 컬럼이 없고,
// community-api-contract.md 1절 CommentResponse에도 수정 시각이 없다). BaseTimeEntity
// (createdAt+updatedAt 쌍 + auditing listener)를 상속하지 않고, id처럼 생성자 기본값으로
// createdAt을 직접 채운다 — 이렇게 하면 순수 Mockito 단위 테스트에서도 값이 바로 채워진다.
@Entity
@Table(name = "community_comment")
@SQLRestriction("deleted_at IS NULL")
class CommunityComment(
	@Id
	val id: UUID = UUID.randomUUID(),
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "post_id", nullable = false)
	val post: CommunityPost,
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "author_id", nullable = false)
	val author: User,
	@Column(nullable = false, columnDefinition = "TEXT")
	val content: String,
) {
	@Column(name = "created_at", nullable = false, updatable = false)
	val createdAt: Instant = Instant.now()

	@Column(name = "deleted_at")
	var deletedAt: Instant? = null
		protected set

	fun softDelete(deletedAt: Instant) {
		require(this.deletedAt == null) { "Comment is already deleted." }
		this.deletedAt = deletedAt
	}
}
