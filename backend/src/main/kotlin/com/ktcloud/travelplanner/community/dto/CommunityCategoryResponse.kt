package com.ktcloud.travelplanner.community.dto

import com.ktcloud.travelplanner.community.model.CommunityCategory

data class CommunityCategoryResponse(
	val code: String,
	val name: String,
	val sortOrder: Int,
) {
	companion object {
		fun from(category: CommunityCategory): CommunityCategoryResponse = CommunityCategoryResponse(
			code = category.code,
			name = category.name,
			sortOrder = category.sortOrder,
		)
	}
}
