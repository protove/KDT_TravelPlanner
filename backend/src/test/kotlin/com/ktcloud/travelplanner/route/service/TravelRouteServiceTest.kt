package com.ktcloud.travelplanner.route.service

import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.route.model.TransportationType
import com.ktcloud.travelplanner.route.port.RouteCalculation
import com.ktcloud.travelplanner.route.port.RouteCalculationPort
import com.ktcloud.travelplanner.route.port.RouteLegCalculation
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNull

class TravelRouteServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val routeCalculationPort = mock(RouteCalculationPort::class.java)
	private val service = TravelRouteService(
		travelRepository,
		travelMemberRepository,
		timelineItemRepository,
		routeCalculationPort,
	)

	@Test
	fun `maps ordered Place ID waypoints and Google legs back to timeline ids`() {
		val travel = travel()
		val first = item(travel, 1, "place-1")
		val unmapped = item(travel, 2, null)
		val third = item(travel, 3, "place-3")
		val fourth = item(travel, 4, "place-4")
		stubTravel(travel, listOf(first, unmapped, third, fourth))
		`when`(
			routeCalculationPort.calculateRoute(
				listOf("place-1", "place-3", "place-4"),
				TransportationType.WALK,
			),
		).thenReturn(
			RouteCalculation(
				encodedPolyline = "polyline",
				encodedPolylines = listOf("polyline"),
				totalDistanceMeters = 1200,
				totalDurationSeconds = 900,
				legs = listOf(RouteLegCalculation(500, 300), RouteLegCalculation(700, 600)),
				warnings = listOf("보행 경로 주의"),
			),
		)

		val response = service.getRoute(TRAVEL_ID, OWNER_ID, 1, TransportationType.WALK)

		assertEquals("polyline", response.encodedPolyline)
		assertEquals(listOf(first.id, third.id), response.legs.map { it.fromTimelineItemId })
		assertEquals(listOf(third.id, fourth.id), response.legs.map { it.toTimelineItemId })
		assertEquals(listOf("보행 경로 주의"), response.warnings)
		verifyNoInteractions(travelMemberRepository)
	}

	@Test
	fun `zero and one route point return an empty route without Google call`() {
		val travel = travel()
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(emptyList(), listOf(item(travel, 1, "only-place")))

		listOf(TransportationType.DRIVE, TransportationType.BICYCLE).forEach { type ->
			val response = service.getRoute(TRAVEL_ID, OWNER_ID, 1, type)
			assertNull(response.encodedPolyline)
			assertEquals(0, response.totalDistanceMeters)
			assertEquals(emptyList(), response.legs)
		}
		verifyNoInteractions(routeCalculationPort)
	}

	@Test
	fun `twenty seven points are accepted and twenty eight are rejected`() {
		val travel = travel()
		val twentySeven = (1..27).map { item(travel, it.toShort(), "place-$it") }
		val calculation = RouteCalculation(
			encodedPolyline = "polyline",
			encodedPolylines = listOf("polyline"),
			totalDistanceMeters = 26,
			totalDurationSeconds = 26,
			legs = List(26) { RouteLegCalculation(1, 1) },
			warnings = emptyList(),
		)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(twentySeven, twentySeven + item(travel, 28, "place-28"))
		`when`(
			routeCalculationPort.calculateRoute(
				twentySeven.map { requireNotNull(it.googlePlaceId) },
				TransportationType.DRIVE,
			),
		).thenReturn(calculation)

		assertEquals(26, service.getRoute(TRAVEL_ID, OWNER_ID, 1, TransportationType.DRIVE).legs.size)
		assertThrows<TooManyRouteWaypointsException> {
			service.getRoute(TRAVEL_ID, OWNER_ID, 1, TransportationType.DRIVE)
		}
		verify(routeCalculationPort).calculateRoute(
			twentySeven.map { requireNotNull(it.googlePlaceId) },
			TransportationType.DRIVE,
		)
	}

	@Test
	fun `access and day validation happen before timeline lookup`() {
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.empty())
		assertThrows<RouteTravelNotFoundException> {
			service.getRoute(TRAVEL_ID, MEMBER_ID, 1, TransportationType.DRIVE)
		}

		val travel = travel()
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID)).thenReturn(null)
		assertThrows<RouteAccessDeniedException> {
			service.getRoute(TRAVEL_ID, MEMBER_ID, 1, TransportationType.DRIVE)
		}
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID)).thenReturn(TravelRole.READ_ONLY)
		assertThrows<InvalidRouteDayNumberException> {
			service.getRoute(TRAVEL_ID, MEMBER_ID, 4, TransportationType.DRIVE)
		}
		verifyNoInteractions(timelineItemRepository, routeCalculationPort)
	}

	private fun stubTravel(travel: Travel, items: List<TimelineItem>) {
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(items)
	}

	private fun travel(): Travel = Travel(
		id = TRAVEL_ID,
		owner = mock(User::class.java).also { `when`(it.id).thenReturn(OWNER_ID) },
		title = "경로 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	private fun item(travel: Travel, order: Short, placeId: String?): TimelineItem = TimelineItem(
		travel = travel,
		dayNumber = 1,
		visitDate = LocalDate.parse("2026-08-01"),
		category = TimelineCategory.OTHER,
		name = "일정 $order",
		googlePlaceId = placeId,
		visitOrder = order,
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000027")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000028")
	}
}
