package com.ktcloud.travelplanner.travel.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.notNullValue
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.post
import org.springframework.transaction.annotation.Transactional
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val entityManager: EntityManager,
) {
	@Test
	fun `authenticated user creates travel as owner and persistence stores dates`() {
		val owner = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(owner.id)).value

		val result = mockMvc.post("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"도쿄 여행","startDate":"2026-08-01","endDate":"2026-08-04"}"""
		}
			.andExpect {
				status { isOk() }
				jsonPath("$.data.travelId", notNullValue())
			}
			.andReturn()

		val responseBody = result.response.contentAsString
		val travelId = UUID.fromString(Regex("\\\"travelId\\\":\\\"([^\\\"]+)\\\"").find(responseBody)!!.groupValues[1])
		entityManager.flush()
		entityManager.clear()
		val travel = travelRepository.findById(travelId).orElseThrow()

		assertEquals(owner.id, travel.owner.id)
		assertEquals("도쿄 여행", travel.title)
		assertEquals(LocalDate.parse("2026-08-01"), travel.startDate)
		assertEquals(LocalDate.parse("2026-08-04"), travel.endDate)
		assertEquals(4, travel.travelDays)
	}

	@Test
	fun `invalid date range returns validation error and does not persist`() {
		val owner = saveUser()
		val accessToken = jwtTokenService.issueAccessToken(requireNotNull(owner.id)).value

		mockMvc.post("/api/v1/travels") {
			header(HttpHeaders.AUTHORIZATION, "Bearer $accessToken")
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"역순 여행","startDate":"2026-08-04","endDate":"2026-08-01"}"""
		}
			.andExpect {
				status { isBadRequest() }
				jsonPath("$.code", equalTo("VALIDATION_ERROR"))
				jsonPath("$.fieldErrors[0].field", equalTo("endDate"))
			}

		assertEquals(0, travelRepository.count())
	}

	@Test
	fun `unauthenticated create request returns unauthorized`() {
		mockMvc.post("/api/v1/travels") {
			contentType = MediaType.APPLICATION_JSON
			content = """{"title":"도쿄 여행","startDate":"2026-08-01","endDate":"2026-08-04"}"""
		}
			.andExpect {
				status { isUnauthorized() }
				jsonPath("$.code", equalTo("UNAUTHORIZED"))
			}
	}

	private fun saveUser(): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "travel-${UUID.randomUUID()}",
			email = "owner@example.com",
			name = "Travel Owner",
		),
	)
}
