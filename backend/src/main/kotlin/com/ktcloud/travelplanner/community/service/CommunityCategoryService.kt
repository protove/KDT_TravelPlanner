package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommunityCategoryResponse
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class CommunityCategoryService(
	private val communityCategoryRepository: CommunityCategoryRepository,
) {
	@Transactional(readOnly = true)
	fun getCategories(): List<CommunityCategoryResponse> =
		communityCategoryRepository.findAllByIsActiveTrueOrderBySortOrderAscIdAsc().map(CommunityCategoryResponse::from)
}
