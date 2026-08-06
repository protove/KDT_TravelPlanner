package com.ktcloud.travelplanner.place.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.place.port.PlaceLocation
import com.ktcloud.travelplanner.place.port.PlaceLocationPort
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.hamcrest.Matchers.equalTo
import org.hamcrest.Matchers.hasSize
import org.junit.jupiter.api.Test
import org.mockito.Mockito.times
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpHeaders
import org.springframework.jdbc.core.JdbcTemplate
import org.springframework.test.context.ActiveProfiles
import org.springframework.test.context.bean.override.mockito.MockitoBean
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.get
import org.springframework.transaction.annotation.Transactional
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelMapPointControllerIntegrationTest(
	@Autowired private val mockMvc: MockMvc,
	@Autowired private val userRepository: UserRepository,
	@Autowired private val travelRepository: TravelRepository,
	@Autowired private val travelMemberRepository: TravelMemberRepository,
	@Autowired private val timelineItemRepository: TimelineItemRepository,
	@Autowired private val jwtTokenService: JwtTokenService,
	@Autowired private val jdbcTemplate: JdbcTemplate,
	@Autowired private val entityManager: EntityManager,
) {
	@MockitoBean
	private lateinit var placeLocationPort: PlaceLocationPort

	@Test
	fun `owner receives ordered points and partial mapping results without storing the response`() {
		val owner = saveUser("map-owner")
		val travel = saveTravel(owner)
		val firstPlaceId = "map-first-${UUID.randomUUID()}"
		val secondPlaceId = "map-second-${UUID.randomUUID()}"
		val missingPlaceId = "map-missing-${UUID.randomUUID()}"
		val first = saveTimelineItem(travel, 1, "도쿄 타워", firstPlaceId)
		val unmapped = saveTimelineItem(travel, 2, "자유 일정", null)
		val second = saveTimelineItem(travel, 3, "도쿄역", secondPlaceId)
		val unresolved = saveTimelineItem(travel, 4, "폐업 장소", missingPlaceId)
		`when`(placeLocationPort.findLocation(firstPlaceId))
			.thenReturn(PlaceLocation(BigDecimal("35.658581"), BigDecimal("139.745433")))
		`when`(placeLocationPort.findLocation(secondPlaceId))
			.thenReturn(PlaceLocation(BigDecimal("35.681236"), BigDecimal("139.767125")))
		`when`(placeLocationPort.findLocation(missingPlaceId)).thenReturn(null)

		getMapPoints(travel, owner, 1)
			.andExpect {
				status { isOk() }
				header { string(HttpHeaders.CACHE_CONTROL, "no-store") }
				jsonPath("$.data.travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.dayNumber", equalTo(1))
				jsonPath("$.data.points", hasSize<Any>(2))
				jsonPath("$.data.points[0].timelineItemId", equalTo(first.id.toString()))
				jsonPath("$.data.points[0].visitOrder", equalTo(1))
				jsonPath("$.data.points[0].name", equalTo("도쿄 타워"))
				jsonPath("$.data.points[0].googlePlaceId", equalTo(firstPlaceId))
				jsonPath("$.data.points[0].latitude", equalTo(35.658581))
				jsonPath("$.data.points[0].longitude", equalTo(139.745433))
				jsonPath("$.data.points[1].timelineItemId", equalTo(second.id.toString()))
				jsonPath("$.data.unmappedTimelineItemIds[0]", equalTo(unmapped.id.toString()))
				jsonPath("$.data.unresolvedTimelineItemIds[0]", equalTo(unresolved.id.toString()))
			}

		getMapPoints(travel, owner, 1).andExpect { status { isOk() } }
		verify(placeLocationPort, times(1)).findLocation(firstPlaceId)
		verify(placeLocationPort, times(1)).findLocation(secondPlaceId)
		verify(placeLocationPort, times(2)).findLocation(missingPlaceId)
	}

	@Test
	fun `owner receives an empty response for a day without timeline items`() {
		val owner = saveUser("map-empty-owner")
		val travel = saveTravel(owner)

		getMapPoints(travel, owner, 2)
			.andExpect {
				status { isOk() }
				jsonPath("$.data.points", hasSize<Any>(0))
				jsonPath("$.data.unmappedTimelineItemIds", hasSize<Any>(0))
				jsonPath("$.data.unresolvedTimelineItemIds", hasSize<Any>(0))
			}
	}

	@Test
	fun `accepted read write and read only members can read map points`() {
		val owner = saveUser("map-member-owner")
		val readWrite = saveUser("map-read-write")
		val readOnly = saveUser("map-read-only")
		val travel = saveTravel(owner)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		getMapPoints(travel, readWrite, 1).andExpect { status { isOk() } }
		getMapPoints(travel, readOnly, 1).andExpect { status { isOk() } }
	}

	@Test
	fun `invalid access day and travel id use common error responses`() {
		val owner = saveUser("map-error-owner")
		val outsider = saveUser("map-outsider")
		val travel = saveTravel(owner)

		getMapPoints(travel, outsider, 1)
			.andExpect {
				status { isForbidden() }
				jsonPath("$.code", equalTo("ACCESS_DENIED"))
			}
		listOf(0, 4).forEach { invalidDay ->
			getMapPoints(travel, owner, invalidDay)
				.andExpect {
					status { isBadRequest() }
					jsonPath("$.code", equalTo("INVALID_REQUEST"))
				}
		}
		mockMvc.get("/api/v1/travels/${UUID.randomUUID()}/map-points") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
			param("dayNumber", "1")
		}.andExpect {
			status { isNotFound() }
			jsonPath("$.code", equalTo("RESOURCE_NOT_FOUND"))
		}
	}

	@Test
	fun `unauthenticated request is rejected`() {
		mockMvc.get("/api/v1/travels/${UUID.randomUUID()}/map-points") {
			param("dayNumber", "1")
		}.andExpect { status { isUnauthorized() } }
	}

	private fun getMapPoints(
		travel: Travel,
		requester: User,
		dayNumber: Int,
	) = mockMvc.get("/api/v1/travels/${travel.id}/map-points") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		param("dayNumber", dayNumber.toString())
	}

	private fun acceptMember(
		travel: Travel,
		user: User,
		role: TravelRole,
	) {
		val member = travelMemberRepository.saveAndFlush(
			TravelMember(
				travel = travel,
				user = user,
				role = role,
				invitedAt = Instant.parse("2026-01-01T00:00:00Z"),
			),
		)
		jdbcTemplate.update("UPDATE planner_members SET status = 'ACCEPTED' WHERE id = ?", member.id)
		entityManager.clear()
	}

	private fun saveTimelineItem(
		travel: Travel,
		visitOrder: Short,
		name: String,
		googlePlaceId: String?,
	): TimelineItem = timelineItemRepository.saveAndFlush(
		TimelineItem(
			travel = travel,
			dayNumber = 1,
			visitDate = LocalDate.parse("2026-08-01"),
			category = TimelineCategory.OTHER,
			name = name,
			googlePlaceId = googlePlaceId,
			visitOrder = visitOrder,
		),
	)

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "map-points-${UUID.randomUUID()}",
		).also { it.completeProfile(nickname, null, null) },
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "지도 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
