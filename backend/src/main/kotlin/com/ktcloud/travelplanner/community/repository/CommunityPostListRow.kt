package com.ktcloud.travelplanner.community.repository

import java.time.Instant
import java.util.UUID

data class CommunityPostListRow(
	val postId: UUID,
	val categoryCode: String,
	val title: String,
	val bodyPreview: String?,
	val authorNickname: String?,
	val authorProfileImageUrl: String?,
	val viewCount: Int,
	val sourceTravelId: UUID?,
	val createdAt: Instant,
)

data class CommunityPostTagNameRow(
	val postId: UUID,
	val tagName: String,
)
