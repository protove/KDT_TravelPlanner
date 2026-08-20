package com.ktcloud.travelplanner.community.model

import com.ktcloud.travelplanner.global.model.BaseTimeEntity
import com.ktcloud.travelplanner.user.model.User
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.JoinTable
import jakarta.persistence.ManyToMany
import jakarta.persistence.ManyToOne
import jakarta.persistence.Table
import jakarta.persistence.Version
import org.hibernate.annotations.JdbcTypeCode
import org.hibernate.annotations.SQLRestriction
import org.hibernate.type.SqlTypes
import java.time.Instant
import java.util.UUID

@Entity
@Table(name = "community_post")
@SQLRestriction("deleted_at IS NULL")
class CommunityPost(
	@Id
	val id: UUID = UUID.randomUUID(),
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "author_id", nullable = false)
	val author: User,
	@ManyToOne(fetch = FetchType.LAZY, optional = false)
	@JoinColumn(name = "category_id", nullable = false)
	var category: CommunityCategory,
	title: String,
	bodyJson: String,
	bodyPreview: String?,
	sourceTravelId: UUID?,
) : BaseTimeEntity() {
	@Column(nullable = false, length = 200)
	var title: String = title
		protected set

	// Hibernate 6 native JSON mapping (SqlTypes.JSON) — String을 있는 그대로 jsonb 컬럼에 직렬화한다.
	@JdbcTypeCode(SqlTypes.JSON)
	@Column(name = "body_json", nullable = false, columnDefinition = "jsonb")
	var bodyJson: String = bodyJson
		protected set

	@Column(name = "body_preview", length = 200)
	var bodyPreview: String? = bodyPreview
		protected set

	@Column(name = "source_travel_id")
	var sourceTravelId: UUID? = sourceTravelId
		protected set

	@Column(name = "view_count", nullable = false)
	var viewCount: Int = 0
		protected set

	@Version
	@Column(nullable = false)
	var version: Int = 0
		protected set

	@Column(name = "deleted_at")
	var deletedAt: Instant? = null
		protected set

	@ManyToMany
	@JoinTable(
		name = "community_post_tag",
		joinColumns = [JoinColumn(name = "post_id")],
		inverseJoinColumns = [JoinColumn(name = "tag_id")],
	)
	var tags: MutableSet<CommunityTag> = mutableSetOf()
		protected set

	fun assignTags(tags: Set<CommunityTag>) {
		this.tags = tags.toMutableSet()
	}
}
