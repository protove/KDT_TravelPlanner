package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdate
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdateRequest
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.times
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TimelineItemOrderUpdateServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val service = TimelineItemOrderUpdateService(
		travelRepository,
		travelMemberRepository,
		timelineItemRepository,
	)

	@Test
	fun `owner reorders a complete item permutation through a temporary order`() {
		val travel = travel(mockUser(OWNER_ID))
		val firstItem = item(travel, FIRST_ITEM_ID, 1)
		val secondItem = item(travel, SECOND_ITEM_ID, 2)
		val thirdItem = item(travel, THIRD_ITEM_ID, 3)
		stubItems(travel, listOf(firstItem, secondItem, thirdItem))

		service.updateTimelineItemOrder(
			TRAVEL_ID,
			OWNER_ID,
			request(FIRST_ITEM_ID to 3, SECOND_ITEM_ID to 1, THIRD_ITEM_ID to 2),
		)

		assertEquals(3, firstItem.visitOrder.toInt())
		assertEquals(1, secondItem.visitOrder.toInt())
		assertEquals(2, thirdItem.visitOrder.toInt())
		verify(timelineItemRepository, times(6)).saveAndFlush(org.mockito.ArgumentMatchers.any())
		verifyNoInteractions(travelMemberRepository)
	}

	@ParameterizedTest
	@ValueSource(ints = [3, 10, 25, 50, 100, 200])
	fun `reverse permutation persistence calls grow by three per swapped pair`(itemCount: Int) {
		val travelRepository = mock(TravelRepository::class.java)
		val travelMemberRepository = mock(TravelMemberRepository::class.java)
		val timelineItemRepository = mock(TimelineItemRepository::class.java)
		val service = TimelineItemOrderUpdateService(
			travelRepository,
			travelMemberRepository,
			timelineItemRepository,
		)
		val travel = travel(mockUser(OWNER_ID))
		val items = (1..itemCount).map { visitOrder ->
			item(
				travel,
				UUID.nameUUIDFromBytes("sql-diagnostic-item-$itemCount-$visitOrder".toByteArray()),
				visitOrder.toShort(),
			)
		}
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(items)

		service.updateTimelineItemOrder(
			TRAVEL_ID,
			OWNER_ID,
			TimelineItemOrderUpdateRequest(
				dayNumber = 1,
				items = items.asReversed().mapIndexed { index, timelineItem ->
					TimelineItemOrderUpdate(timelineItem.id, index + 1)
				},
			),
		)

		verify(timelineItemRepository, times(3 * (itemCount / 2)))
			.saveAndFlush(org.mockito.ArgumentMatchers.any())
	}

	@Test
	fun `duplicate missing and another day item requests are rejected before writes`() {
		val travel = travel(mockUser(OWNER_ID))
		val items = listOf(item(travel, FIRST_ITEM_ID, 1), item(travel, SECOND_ITEM_ID, 2))
		stubItems(travel, items)

		listOf(
			request(FIRST_ITEM_ID to 1, FIRST_ITEM_ID to 2),
			request(FIRST_ITEM_ID to 1),
			request(FIRST_ITEM_ID to 1, OTHER_ITEM_ID to 2),
			request(FIRST_ITEM_ID to 1, SECOND_ITEM_ID to 1),
		).forEach { invalidRequest ->
			assertThrows<InvalidTimelineItemOrderException> {
				service.updateTimelineItemOrder(TRAVEL_ID, OWNER_ID, invalidRequest)
			}
		}

		verify(timelineItemRepository, never()).saveAndFlush(org.mockito.ArgumentMatchers.any())
	}

	@Test
	fun `read only member is rejected while read write is accepted`() {
		val travel = travel(mockUser(OWNER_ID))
		val item = item(travel, FIRST_ITEM_ID, 1)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID))
			.thenReturn(false, true)

		assertThrows<TimelineItemOrderUpdateAccessDeniedException> {
			service.updateTimelineItemOrder(TRAVEL_ID, MEMBER_ID, request(FIRST_ITEM_ID to 1))
		}

		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(listOf(item))
		service.updateTimelineItemOrder(TRAVEL_ID, MEMBER_ID, request(FIRST_ITEM_ID to 1))
		verify(timelineItemRepository, never()).saveAndFlush(item)
	}

	private fun stubItems(
		travel: Travel,
		items: List<TimelineItem>,
	) {
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdAndDayNumberOrderByVisitOrderAsc(TRAVEL_ID, 1))
			.thenReturn(items)
	}

	private fun request(vararg items: Pair<UUID, Int>): TimelineItemOrderUpdateRequest =
		TimelineItemOrderUpdateRequest(
			dayNumber = 1,
			items = items.map { (itemId, visitOrder) -> TimelineItemOrderUpdate(itemId, visitOrder) },
		)

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = Travel(
		id = TRAVEL_ID,
		owner = owner,
		title = "타임라인 순서 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-03"),
	)

	private fun item(
		travel: Travel,
		itemId: UUID,
		visitOrder: Short,
	): TimelineItem = TimelineItem(
		id = itemId,
		travel = travel,
		dayNumber = 1,
		visitDate = LocalDate.parse("2026-08-01"),
		category = TimelineCategory.OTHER,
		name = "순서 테스트 일정",
		visitOrder = visitOrder,
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000025")
		private val FIRST_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000125")
		private val SECOND_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000225")
		private val THIRD_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000325")
		private val OTHER_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000425")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
	}
}
