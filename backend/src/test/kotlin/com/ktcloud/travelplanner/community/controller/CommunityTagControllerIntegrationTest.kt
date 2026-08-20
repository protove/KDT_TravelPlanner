package com.ktcloud.travelplanner.community.controller

import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import org.hamcrest.Matchers.equalTo
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
class CommunityTagControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val communityTagRepository: CommunityTagRepository,
) {
	@BeforeEach
	fun setUpTags() {
		communityTagRepository.deleteAllInBatch()
		listOf("제주도", "제주맛집", "오사카", "부산").forEach {
			communityTagRepository.save(CommunityTag(it))
		}
	}

	@Test
	fun `returns tags whose name starts with the keyword regardless of case`() {
		mockMvc.get("/api/v1/community/tags") {
			param("keyword", "제주")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(2))
				jsonPath("$.data[0]", equalTo("제주도"))
				jsonPath("$.data[1]", equalTo("제주맛집"))
			}
	}

	@Test
	fun `returns tags matching an english keyword ignoring case`() {
		communityTagRepository.save(CommunityTag("Osaka"))

		mockMvc.get("/api/v1/community/tags") {
			param("keyword", "osa")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(1))
				jsonPath("$.data[0]", equalTo("Osaka"))
			}
	}

	@Test
	fun `defaults to size 10 and does not require authentication`() {
		mockMvc.get("/api/v1/community/tags")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(4))
			}
	}

	@Test
	fun `clamps size to the requested limit`() {
		mockMvc.get("/api/v1/community/tags") {
			param("size", "2")
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.length()", equalTo(2))
			}
	}
}
