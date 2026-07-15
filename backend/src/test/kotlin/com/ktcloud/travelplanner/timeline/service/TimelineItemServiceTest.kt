package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.dto.TimelineItemCreateRequest
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.math.BigDecimal
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TimelineItemServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val cityRepository = mock(CityRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val service = TimelineItemService(
		travelRepository,
		travelMemberRepository,
		cityRepository,
		timelineItemRepository,
	)

	@Test
	fun `owner creates timeline item with normalized optional values`() {
		val travel = travel(mockUser(OWNER_ID))
		lateinit var savedItem: TimelineItem
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrder(TRAVEL_ID, 1, 1))
			.thenReturn(false)
		`when`(timelineItemRepository.saveAndFlush(any(TimelineItem::class.java))).thenAnswer {
			it.getArgument<TimelineItem>(0).also { item -> savedItem = item }
		}

		val response = service.createTimelineItem(TRAVEL_ID, OWNER_ID, request())

		assertEquals(savedItem.id, response.timelineItemId)
		assertEquals("도쿄 타워", savedItem.name)
		assertEquals("저녁 방문", savedItem.memo)
		verifyNoInteractions(cityRepository, travelMemberRepository)
	}

	@Test
	fun `accepted read write member can create but other member cannot`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID))
			.thenReturn(true)
		`when`(timelineItemRepository.saveAndFlush(any(TimelineItem::class.java))).thenAnswer {
			it.getArgument(0)
		}

		service.createTimelineItem(TRAVEL_ID, MEMBER_ID, request())

		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, READ_ONLY_ID))
			.thenReturn(false)
		assertThrows<TimelineWriteAccessDeniedException> {
			service.createTimelineItem(TRAVEL_ID, READ_ONLY_ID, request())
		}
	}

	@Test
	fun `invalid day date and duplicate visit order are rejected`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrder(TRAVEL_ID, 2, 1))
			.thenReturn(false)

		assertThrows<InvalidTimelineItemException> {
			service.createTimelineItem(
				TRAVEL_ID,
				OWNER_ID,
				request(dayNumber = 2, visitDate = LocalDate.parse("2026-08-01")),
			)
		}

		`when`(timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrder(TRAVEL_ID, 1, 1))
			.thenReturn(true)
		assertThrows<DuplicateTimelineOrderException> {
			service.createTimelineItem(TRAVEL_ID, OWNER_ID, request())
		}
		verify(timelineItemRepository, never()).saveAndFlush(any(TimelineItem::class.java))
	}

	private fun request(
		dayNumber: Int = 1,
		visitDate: LocalDate = LocalDate.parse("2026-08-01"),
	) = TimelineItemCreateRequest(
		dayNumber = dayNumber,
		visitDate = visitDate,
		cityId = null,
		category = TimelineCategory.ATTRACTION,
		foodSubcategory = null,
		name = " 도쿄 타워 ",
		googlePlaceId = "google-place-id",
		latitude = BigDecimal("35.658581"),
		longitude = BigDecimal("139.745433"),
		rating = BigDecimal("4.5"),
		visitOrder = 1,
		memo = " 저녁 방문 ",
	)

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = Travel(
		id = TRAVEL_ID,
		owner = owner,
		title = "타임라인 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000022")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
		private val READ_ONLY_ID = UUID.fromString("00000000-0000-0000-0000-000000000003")
	}
}
