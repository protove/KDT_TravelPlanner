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

// community_comment는 작성/수정/소프트삭제를 지원한다. updated_at은 V21에서 추가된 nullable
// 컬럼 — null이면 "한 번도 수정 안 됨"을 뜻한다(수정 시에만 채워짐, CommentResponse의
// "(수정됨)" 표시에 그대로 쓰인다). BaseTimeEntity(auditing listener 기반)를 상속하지 않고,
// id처럼 생성자 기본값으로 createdAt을 직접 채운다 — 순수 Mockito 단위 테스트에서도 값이
// 바로 채워지게 하기 위함(auditing listener는 실제 persist 시점에만 동작해서 mock 환경에서
// lateinit 미초기화로 터진다).
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
	content: String,
) {
	@Column(nullable = false, columnDefinition = "TEXT")
	var content: String = content
		protected set

	@Column(name = "created_at", nullable = false, updatable = false)
	val createdAt: Instant = Instant.now()

	@Column(name = "updated_at")
	var updatedAt: Instant? = null
		protected set

	@Column(name = "deleted_at")
	var deletedAt: Instant? = null
		protected set

	fun edit(
		content: String,
		updatedAt: Instant,
	) {
		this.content = content
		this.updatedAt = updatedAt
	}

	fun softDelete(deletedAt: Instant) {
		require(this.deletedAt == null) { "Comment is already deleted." }
		this.deletedAt = deletedAt
	}
}
