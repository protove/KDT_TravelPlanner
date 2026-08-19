package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.model.CommunityCategory
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import org.junit.jupiter.api.Test
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import kotlin.test.assertEquals

class CommunityCategoryServiceTest {
	private val communityCategoryRepository = mock(CommunityCategoryRepository::class.java)
	private val service = CommunityCategoryService(communityCategoryRepository)

	@Test
	fun `maps active categories ordered by sort order into response DTOs`() {
		val categories = listOf(
			CommunityCategory(id = 1, code = "TRAVEL_REVIEW", name = "여행후기", sortOrder = 1),
			CommunityCategory(id = 2, code = "FREE", name = "자유게시판", sortOrder = 2),
		)
		`when`(communityCategoryRepository.findAllByIsActiveTrueOrderBySortOrderAscIdAsc()).thenReturn(categories)

		val response = service.getCategories()

		assertEquals(
			listOf(
				Triple("TRAVEL_REVIEW", "여행후기", 1),
				Triple("FREE", "자유게시판", 2),
			),
			response.map { Triple(it.code, it.name, it.sortOrder) },
		)
	}
}
