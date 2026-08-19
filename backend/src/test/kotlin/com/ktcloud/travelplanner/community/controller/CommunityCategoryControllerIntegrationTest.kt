package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.model.CommunityCategory
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.hasSize
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class CommunityCategoryControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val communityCategoryRepository: CommunityCategoryRepository,
) {
	@BeforeEach
	fun setUpCategories() {
		communityCategoryRepository.deleteAllInBatch()

		communityCategoryRepository.save(CommunityCategory(id = 2, code = "FREE", name = "자유게시판", sortOrder = 2))
		communityCategoryRepository.save(CommunityCategory(id = 1, code = "TRAVEL_REVIEW", name = "여행후기", sortOrder = 1))
		communityCategoryRepository.save(
			CommunityCategory(id = 3, code = "HIDDEN", name = "숨김 카테고리", sortOrder = 0, isActive = false),
		)
	}

	@Test
	fun `lists active categories ordered by sort order without authentication`() {
		mockMvc.get("/api/v1/community/categories")
			.andExpect {
				status { isOk() }
				jsonPath("$.data", hasSize<Any>(2))
				jsonPath("$.data[0].code", equalTo("TRAVEL_REVIEW"))
				jsonPath("$.data[0].name", equalTo("여행후기"))
				jsonPath("$.data[0].sortOrder", equalTo(1))
				jsonPath("$.data[1].code", equalTo("FREE"))
			}
	}
}
