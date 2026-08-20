package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import org.springframework.data.domain.PageRequest
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class CommunityTagService(
	private val communityTagRepository: CommunityTagRepository,
) {
	@Transactional(readOnly = true)
	fun searchTagNames(keyword: String, size: Int): List<String> {
		val clampedSize = size.coerceIn(1, MAX_SIZE)
		return communityTagRepository
			.findByNameStartingWithIgnoreCaseOrderByName(keyword.trim(), PageRequest.of(0, clampedSize))
			.map { it.name }
	}

	companion object {
		private const val MAX_SIZE = 50
	}
}
