package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.dto.TimelineItemUpdateRequest
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.global.dto.PatchField
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertNull

class TimelineItemUpdateServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val cityRepository = mock(CityRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val service = TimelineItemUpdateService(
		travelRepository,
		travelMemberRepository,
		cityRepository,
		timelineItemRepository,
	)

	@Test
	fun `owner partially updates item and explicitly clears nullable fields`() {
		val travel = travel(mockUser(OWNER_ID))
		val item = item(travel)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(item)
		`when`(timelineItemRepository.saveAndFlush(item)).thenReturn(item)

		val response = service.updateTimelineItem(
			TRAVEL_ID,
			ITEM_ID,
			OWNER_ID,
			TimelineItemUpdateRequest(
				name = PatchField.Present(" 수정 일정 "),
				memo = PatchField.Present(null),
			),
		)

		assertEquals("수정 일정", response.name)
		assertNull(response.memo)
		verifyNoInteractions(travelMemberRepository, cityRepository)
	}

	@Test
	fun `non writer and item from another travel are rejected`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID)).thenReturn(false)
		assertThrows<TimelineItemUpdateAccessDeniedException> {
			service.updateTimelineItem(TRAVEL_ID, ITEM_ID, MEMBER_ID, TimelineItemUpdateRequest())
		}

		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(null)
		assertThrows<TimelineItemNotFoundException> {
			service.updateTimelineItem(TRAVEL_ID, ITEM_ID, OWNER_ID, TimelineItemUpdateRequest())
		}
		verify(timelineItemRepository, never()).saveAndFlush(org.mockito.ArgumentMatchers.any())
	}

	@Test
	fun `duplicate target order is conflict`() {
		val travel = travel(mockUser(OWNER_ID))
		val item = item(travel)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(item)
		`when`(timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrderAndIdNot(TRAVEL_ID, 1, 2, ITEM_ID))
			.thenReturn(true)

		assertThrows<TimelineItemOrderConflictException> {
			service.updateTimelineItem(
				TRAVEL_ID,
				ITEM_ID,
				OWNER_ID,
				TimelineItemUpdateRequest(visitOrder = PatchField.Present(2)),
			)
		}
		assertEquals(1, item.visitOrder)
		verify(timelineItemRepository, never()).saveAndFlush(item)
	}

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = Travel(
		id = TRAVEL_ID,
		owner = owner,
		title = "타임라인 수정 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	private fun item(travel: Travel): TimelineItem = TimelineItem(
		id = ITEM_ID,
		travel = travel,
		dayNumber = 1,
		visitDate = LocalDate.parse("2026-08-01"),
		category = TimelineCategory.OTHER,
		name = "기존 일정",
		visitOrder = 1,
		memo = "기존 메모",
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000023")
		private val ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000123")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
	}
}
