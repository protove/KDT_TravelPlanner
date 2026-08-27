package com.ktcloud.travelplanner.route.controller

import com.ktcloud.travelplanner.global.security.JwtTokenService
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculation
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
import com.ktcloud.travelplanner.route.port.RouteLegCalculation
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
import org.mockito.Mockito.verifyNoInteractions
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
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@ActiveProfiles("test")
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelRouteControllerIntegrationTest(
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
	private lateinit var routeCalculationPort: RouteCalculationPort

	@Test
	fun `owner receives mapped route legs warnings and no store header`() {
		val owner = saveUser("route-owner")
		val travel = saveTravel(owner)
		val first = saveItem(travel, 1, "place-1")
		saveItem(travel, 2, null)
		val third = saveItem(travel, 3, "place-3")
		`when`(routeCalculationPort.calculateRoute(listOf("place-1", "place-3"), TransportationType.WALK))
			.thenReturn(
				RouteCalculation(
					encodedPolyline = "encoded-polyline",
					encodedPolylines = listOf("encoded-polyline"),
					totalDistanceMeters = 12400,
					totalDurationSeconds = 2100,
					legs = listOf(RouteLegCalculation(12400, 2100)),
					warnings = listOf("보행 경로 주의"),
				),
			)

		getRoute(travel, owner, 1, "WALK")
			.andExpect {
				status { isOk() }
				header { string(HttpHeaders.CACHE_CONTROL, "no-store") }
				jsonPath("$.data.travelId", equalTo(travel.id.toString()))
				jsonPath("$.data.dayNumber", equalTo(1))
				jsonPath("$.data.transportationType", equalTo("WALK"))
				jsonPath("$.data.encodedPolyline", equalTo("encoded-polyline"))
				jsonPath("$.data.totalDistanceMeters", equalTo(12400))
				jsonPath("$.data.totalDurationSeconds", equalTo(2100))
				jsonPath("$.data.legs", hasSize<Any>(1))
				jsonPath("$.data.legs[0].fromTimelineItemId", equalTo(first.id.toString()))
				jsonPath("$.data.legs[0].toTimelineItemId", equalTo(third.id.toString()))
				jsonPath("$.data.warnings[0]", equalTo("보행 경로 주의"))
			}
	}

	@Test
	fun `empty day and one point return zero route without provider call`() {
		val owner = saveUser("route-empty-owner")
		val travel = saveTravel(owner)

		getRoute(travel, owner, 1, "DRIVE")
			.andExpect {
				status { isOk() }
				jsonPath("$.data.encodedPolyline") { isEmpty() }
				jsonPath("$.data.totalDistanceMeters", equalTo(0))
				jsonPath("$.data.legs", hasSize<Any>(0))
			}
		saveItem(travel, 1, "only-place")
		getRoute(travel, owner, 1, "BICYCLE").andExpect { status { isOk() } }
		verifyNoInteractions(routeCalculationPort)
	}

	@Test
	fun `accepted members can read while outsider and invalid inputs are rejected`() {
		val owner = saveUser("route-access-owner")
		val readWrite = saveUser("route-read-write")
		val readOnly = saveUser("route-read-only")
		val outsider = saveUser("route-outsider")
		val travel = saveTravel(owner)
		acceptMember(travel, readWrite, TravelRole.READ_WRITE)
		acceptMember(travel, readOnly, TravelRole.READ_ONLY)

		getRoute(travel, readWrite, 1, "DRIVE").andExpect { status { isOk() } }
		getRoute(travel, readOnly, 1, "DRIVE").andExpect { status { isOk() } }
		getRoute(travel, outsider, 1, "DRIVE").andExpect { status { isForbidden() } }
		getRoute(travel, owner, 0, "DRIVE").andExpect { status { isBadRequest() } }
		getRoute(travel, owner, 4, "DRIVE").andExpect { status { isBadRequest() } }
		getRoute(travel, owner, 1, "TRANSIT").andExpect { status { isBadRequest() } }
	}

	@Test
	fun `unauthenticated and unknown travel requests are rejected`() {
		val owner = saveUser("route-not-found-owner")
		mockMvc.get("/api/v1/travels/${UUID.randomUUID()}/routes") {
			param("dayNumber", "1")
			param("transportationType", "DRIVE")
		}.andExpect { status { isUnauthorized() } }
		mockMvc.get("/api/v1/travels/${UUID.randomUUID()}/routes") {
			header(HttpHeaders.AUTHORIZATION, bearer(owner))
			param("dayNumber", "1")
			param("transportationType", "DRIVE")
		}.andExpect { status { isNotFound() } }
	}

	private fun getRoute(
		travel: Travel,
		requester: User,
		dayNumber: Int,
		transportationType: String,
	) = mockMvc.get("/api/v1/travels/${travel.id}/routes") {
		header(HttpHeaders.AUTHORIZATION, bearer(requester))
		param("dayNumber", dayNumber.toString())
		param("transportationType", transportationType)
	}

	private fun acceptMember(travel: Travel, user: User, role: TravelRole) {
		val member = travelMemberRepository.saveAndFlush(
			TravelMember(travel = travel, user = user, role = role, invitedAt = Instant.parse("2026-01-01T00:00:00Z")),
		)
		jdbcTemplate.update("UPDATE planner_members SET status = 'ACCEPTED' WHERE id = ?", member.id)
		entityManager.clear()
	}

	private fun saveItem(travel: Travel, order: Short, placeId: String?): TimelineItem =
		timelineItemRepository.saveAndFlush(
			TimelineItem(
				travel = travel,
				dayNumber = 1,
				visitDate = LocalDate.parse("2026-08-01"),
				category = TimelineCategory.OTHER,
				name = "경로 일정 $order",
				googlePlaceId = placeId,
				visitOrder = order,
			),
		)

	private fun bearer(user: User): String =
		"Bearer ${jwtTokenService.issueAccessToken(requireNotNull(user.id)).value}"

	private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
		User(OAuthProvider.GOOGLE, "route-${UUID.randomUUID()}").also {
			it.completeProfile(nickname, null, null)
		},
	)

	private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
		Travel(
			owner = owner,
			title = "경로 여행",
			startDate = LocalDate.parse("2026-08-01"),
			endDate = LocalDate.parse("2026-08-03"),
		),
	)
}
