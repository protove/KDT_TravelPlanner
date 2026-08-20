package com.ktcloud.travelplanner.place.service

import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.place.port.PlaceLocation
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
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.math.BigDecimal
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TravelMapPointServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val placeLocationService = mock(PlaceLocationService::class.java)

	private val service = TravelMapPointService(
		travelRepository,
		travelMemberRepository,
		timelineItemRepository,
		placeLocationService,
	)

	@Test
	fun `owner receives resolved points and separate unmapped and unresolved ids in visit order`() {
		val travel = travel(OWNER_ID)
		val first = timelineItem(
			travel = travel,
			visitOrder = 1,
			name = "도쿄 타워",
			googlePlaceId = "place-1",
		)
		val unmapped = timelineItem(
			travel = travel,
			visitOrder = 2,
			name = "자유 일정",
			googlePlaceId = null,
		)
		val unresolved = timelineItem(
			travel = travel,
			visitOrder = 3,
			name = "폐업 장소",
			googlePlaceId = "place-missing",
		)
		val fourth = timelineItem(
			travel = travel,
			visitOrder = 4,
			name = "도쿄역",
			googlePlaceId = "place-4",
		)

		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(listOf(first, unmapped, unresolved, fourth))
		`when`(placeLocationService.getLocation("place-1"))
			.thenReturn(
				PlaceLocation(
					BigDecimal("35.658581"),
					BigDecimal("139.745433"),
				),
			)
		`when`(placeLocationService.getLocation("place-missing"))
			.thenReturn(null)
		`when`(placeLocationService.getLocation("place-4"))
			.thenReturn(
				PlaceLocation(
					BigDecimal("35.681236"),
					BigDecimal("139.767125"),
				),
			)

		val response = service.getMapPoints(TRAVEL_ID, OWNER_ID, 1)

		assertEquals(
			listOf(first.id, fourth.id),
			response.points.map { it.timelineItemId },
		)
		assertEquals(
			listOf(1, 4),
			response.points.map { it.visitOrder },
		)
		assertEquals(
			listOf(unmapped.id),
			response.unmappedTimelineItemIds,
		)
		assertEquals(
			listOf(unresolved.id),
			response.unresolvedTimelineItemIds,
		)
		verifyNoInteractions(travelMemberRepository)
	}

	@Test
	fun `map points include unassigned places together with requested day`() {
		val travel = travel(OWNER_ID)

		val assigned = timelineItem(
			travel = travel,
			visitOrder = 1,
			name = "덕수궁",
			googlePlaceId = "place-assigned",
			dayNumber = 1,
		)
		val unassigned = timelineItem(
			travel = travel,
			visitOrder = 2,
			name = "대한민국역사박물관",
			googlePlaceId = "place-unassigned",
			dayNumber = null,
		)
		val otherDay = timelineItem(
			travel = travel,
			visitOrder = 1,
			name = "다른 날짜 장소",
			googlePlaceId = "place-day-2",
			dayNumber = 2,
		)

		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(listOf(unassigned, assigned, otherDay))
		`when`(placeLocationService.getLocation("place-assigned"))
			.thenReturn(
				PlaceLocation(
					BigDecimal("37.565804"),
					BigDecimal("126.975146"),
				),
			)
		`when`(placeLocationService.getLocation("place-unassigned"))
			.thenReturn(
				PlaceLocation(
					BigDecimal("37.573714"),
					BigDecimal("126.978913"),
				),
			)

		val response = service.getMapPoints(TRAVEL_ID, OWNER_ID, 1)

		assertEquals(
			setOf(assigned.id, unassigned.id),
			response.points.map { it.timelineItemId }.toSet(),
		)
	}

	@Test
	fun `accepted read only participant can read an empty map day`() {
		val travel = travel(OWNER_ID)

		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID))
			.thenReturn(TravelRole.READ_ONLY)
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(emptyList())

		val response = service.getMapPoints(TRAVEL_ID, MEMBER_ID, 2)

		assertEquals(2, response.dayNumber)
		assertEquals(emptyList(), response.points)
		assertEquals(emptyList(), response.unmappedTimelineItemIds)
		assertEquals(emptyList(), response.unresolvedTimelineItemIds)
		verifyNoInteractions(placeLocationService)
	}

	@Test
	fun `missing travel is rejected before permission and timeline lookup`() {
		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.empty())

		assertThrows<MapPointTravelNotFoundException> {
			service.getMapPoints(TRAVEL_ID, MEMBER_ID, 1)
		}

		verifyNoInteractions(
			travelMemberRepository,
			timelineItemRepository,
			placeLocationService,
		)
	}

	@Test
	fun `non participant is rejected before timeline and provider lookup`() {
		val travel = travel(OWNER_ID)

		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID))
			.thenReturn(null)

		assertThrows<MapPointAccessDeniedException> {
			service.getMapPoints(TRAVEL_ID, MEMBER_ID, 1)
		}

		verifyNoInteractions(
			timelineItemRepository,
			placeLocationService,
		)
	}

	@Test
	fun `day number outside travel period is rejected before timeline lookup`() {
		val travel = travel(OWNER_ID)

		`when`(travelRepository.findById(TRAVEL_ID))
			.thenReturn(Optional.of(travel))

		assertThrows<InvalidMapDayNumberException> {
			service.getMapPoints(TRAVEL_ID, OWNER_ID, 0)
		}
		assertThrows<InvalidMapDayNumberException> {
			service.getMapPoints(TRAVEL_ID, OWNER_ID, 4)
		}

		verifyNoInteractions(
			timelineItemRepository,
			placeLocationService,
		)
	}

	private fun travel(ownerId: UUID): Travel = Travel(
		id = TRAVEL_ID,
		owner = mockUser(ownerId),
		title = "지도 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	private fun timelineItem(
		travel: Travel,
		visitOrder: Short,
		name: String,
		googlePlaceId: String?,
		dayNumber: Short? = 1,
	): TimelineItem = TimelineItem(
		travel = travel,
		dayNumber = dayNumber,
		visitDate = dayNumber?.let {
			travel.startDate.plusDays(it.toLong() - 1)
		},
		category = TimelineCategory.ATTRACTION,
		name = name,
		googlePlaceId = googlePlaceId,
		visitOrder = visitOrder,
	)

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000122")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000012")
	}
}