package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdate
import com.ktcloud.travelplanner.timeline.dto.TimelineItemOrderUpdateRequest
import com.ktcloud.travelplanner.timeline.repository.TimelineItemOrderRepository
import com.ktcloud.travelplanner.timeline.repository.TimelineItemOrderSnapshot
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.params.ParameterizedTest
import org.junit.jupiter.params.provider.ValueSource
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.times
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.verifyNoMoreInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TimelineItemOrderUpdateServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemOrderRepository = mock(TimelineItemOrderRepository::class.java)
	private val service = TimelineItemOrderUpdateService(
		travelRepository,
		travelMemberRepository,
		timelineItemOrderRepository,
	)

	@Test
	fun `owner reverse maps the complete permutation to one bulk update`() {
		val travel = travel(mockUser(OWNER_ID))
		stubSnapshots(travel, snapshots(FIRST_ITEM_ID, SECOND_ITEM_ID, THIRD_ITEM_ID))

		service.updateTimelineItemOrder(
			TRAVEL_ID,
			OWNER_ID,
			request(FIRST_ITEM_ID to 3, SECOND_ITEM_ID to 1, THIRD_ITEM_ID to 2),
		)

		verify(timelineItemOrderRepository).updateVisitOrders(
			TRAVEL_ID,
			1,
			listOf(SECOND_ITEM_ID, THIRD_ITEM_ID, FIRST_ITEM_ID),
			listOf(1, 2, 3).map(Int::toShort),
		)
		verifyNoInteractions(travelMemberRepository)
	}

	@ParameterizedTest
	@ValueSource(ints = [3, 10, 25, 50, 100, 200])
	fun `reverse permutation performs one repository update regardless of item count`(itemCount: Int) {
		val travelRepository = mock(TravelRepository::class.java)
		val travelMemberRepository = mock(TravelMemberRepository::class.java)
		val timelineItemOrderRepository = mock(TimelineItemOrderRepository::class.java)
		val service = TimelineItemOrderUpdateService(
			travelRepository,
			travelMemberRepository,
			timelineItemOrderRepository,
		)
		val travel = travel(mockUser(OWNER_ID))
		val snapshots = (1..itemCount).map { visitOrder ->
			TimelineItemOrderSnapshot(
				itemId = UUID.nameUUIDFromBytes("sql-diagnostic-item-$itemCount-$visitOrder".toByteArray()),
				visitOrder = visitOrder.toShort(),
			)
		}
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemOrderRepository.findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1))
			.thenReturn(snapshots)

		service.updateTimelineItemOrder(
			TRAVEL_ID,
			OWNER_ID,
			TimelineItemOrderUpdateRequest(
				dayNumber = 1,
				items = snapshots.asReversed().mapIndexed { index, snapshot ->
					TimelineItemOrderUpdate(snapshot.itemId, index + 1)
				},
			),
		)

		verify(timelineItemOrderRepository, times(1)).updateVisitOrders(
			TRAVEL_ID,
			1,
			snapshots.asReversed().map(TimelineItemOrderSnapshot::itemId),
			(1..itemCount).map(Int::toShort),
		)
	}

	@Test
	fun `canonical order returns without a repository write`() {
		val travel = travel(mockUser(OWNER_ID))
		stubSnapshots(travel, snapshots(FIRST_ITEM_ID, SECOND_ITEM_ID, THIRD_ITEM_ID))

		service.updateTimelineItemOrder(
			TRAVEL_ID,
			OWNER_ID,
			request(FIRST_ITEM_ID to 1, SECOND_ITEM_ID to 2, THIRD_ITEM_ID to 3),
		)

		verify(timelineItemOrderRepository).findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1)
		verifyNoMoreInteractions(timelineItemOrderRepository)
	}

	@Test
	fun `duplicate missing and another day item requests are rejected before writes`() {
		val travel = travel(mockUser(OWNER_ID))
		stubSnapshots(travel, snapshots(FIRST_ITEM_ID, SECOND_ITEM_ID))

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

		verify(timelineItemOrderRepository, times(4))
			.findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1)
		verifyNoMoreInteractions(timelineItemOrderRepository)
	}

	@Test
	fun `read only member is rejected while read write member can use canonical order`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID))
			.thenReturn(false, true)

		assertThrows<TimelineItemOrderUpdateAccessDeniedException> {
			service.updateTimelineItemOrder(
				TRAVEL_ID,
				MEMBER_ID,
				request(FIRST_ITEM_ID to 1),
			)
		}

		`when`(timelineItemOrderRepository.findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1))
			.thenReturn(snapshots(FIRST_ITEM_ID))
		service.updateTimelineItemOrder(TRAVEL_ID, MEMBER_ID, request(FIRST_ITEM_ID to 1))
		verify(timelineItemOrderRepository).findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1)
		verifyNoMoreInteractions(timelineItemOrderRepository)
	}

	private fun stubSnapshots(
		travel: Travel,
		snapshots: List<TimelineItemOrderSnapshot>,
	) {
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemOrderRepository.findLockedByTravelIdAndDayNumber(TRAVEL_ID, 1))
			.thenReturn(snapshots)
	}

	private fun snapshots(vararg itemIds: UUID): List<TimelineItemOrderSnapshot> =
		itemIds.mapIndexed { index, itemId -> TimelineItemOrderSnapshot(itemId, (index + 1).toShort()) }

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
