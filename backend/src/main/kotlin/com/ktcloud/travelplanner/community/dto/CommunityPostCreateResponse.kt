package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.model.CommunityPost
import java.util.UUID

data class CommunityPostCreateResponse(
	val postId: UUID,
) {
	companion object {
		fun from(post: CommunityPost): CommunityPostCreateResponse = CommunityPostCreateResponse(post.id)
	}
}
