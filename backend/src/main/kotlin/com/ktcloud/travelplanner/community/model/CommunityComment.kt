package com.ktcloud.travelplanner.community.model

import com.ktcloud.travelplanner.user.model.User
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.ManyToOne
import jakarta.persistence.PostLoad
import jakarta.persistence.PrePersist
import jakarta.persistence.Table
import jakarta.persistence.Transient
import org.hibernate.annotations.SQLRestriction
import org.springframework.data.domain.Persistable
import java.time.Instant
import java.util.UUID

// community_comment는 작성/수정/소프트삭제를 지원한다. updated_at은 V21에서 추가된 nullable
// 컬럼 — null이면 "한 번도 수정 안 됨"을 뜻한다(수정 시에만 채워짐, CommentResponse의
// "(수정됨)" 표시에 그대로 쓰인다). BaseTimeEntity(auditing listener 기반)를 상속하지 않고,
// id처럼 생성자 기본값으로 createdAt을 직접 채운다 — 순수 Mockito 단위 테스트에서도 값이
// 바로 채워지게 하기 위함(auditing listener는 실제 persist 시점에만 동작해서 mock 환경에서
// lateinit 미초기화로 터진다).
//
// Persistable을 구현하는 이유: @Id를 @GeneratedValue 없이 생성자 기본값(UUID.randomUUID())으로
// 미리 채우면, @Version도 없는 이 엔티티에 대해 Spring Data JPA의 기본 isNew() 판정(= "id가
// null이면 새 엔티티")이 항상 false로 나온다 — 그러면 save()가 persist() 대신 merge()를 호출하는데,
// DB에 없는 새 row를 merge()하면 insert 없이 조용히 아무 일도 안 일어난다("작성 성공" 응답은
// 오지만 실제로는 저장이 안 됨). isNew()를 트랜지언트 플래그로 직접 관리해서 이 문제를 피한다.
@Entity
@Table(name = "community_comment")
@SQLRestriction("deleted_at IS NULL")
class CommunityComment(
	@Id
	// getId()는 Persistable.getId()의 오버라이드로 아래에 따로 선언한다 — 이 프로퍼티의
	// 기본 게터가 같은 이름(getId)으로 생성되면 JVM 시그니처가 충돌해서 컴파일이 안 된다.
	@get:JvmName("getIdField")
	val id: UUID = UUID.randomUUID(),
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "post_id", nullable = false)
	val post: CommunityPost,
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "author_id", nullable = false)
	val author: User,
	content: String,
) : Persistable<UUID> {
	@Transient
	private var isNew: Boolean = true

	override fun getId(): UUID = id

	override fun isNew(): Boolean = isNew

	@PrePersist
	@PostLoad
	fun markNotNew() {
		isNew = false
	}

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
