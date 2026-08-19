package com.ktcloud.travelplanner.community.model

import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.Id
import jakarta.persistence.Table

@Entity
@Table(name = "community_category")
class CommunityCategory(
	@Id
	val id: Short,
	@Column(nullable = false, length = 30)
	val code: String,
	@Column(nullable = false, length = 50)
	val name: String,
	@Column(name = "sort_order", nullable = false)
	val sortOrder: Int,
	@Column(name = "is_active", nullable = false)
	val isActive: Boolean,
)
