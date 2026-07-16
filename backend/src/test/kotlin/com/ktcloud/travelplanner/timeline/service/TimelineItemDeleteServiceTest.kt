package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.inOrder
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TimelineItemDeleteServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val service = TimelineItemDeleteService(
		travelRepository,
		travelMemberRepository,
		timelineItemRepository,
	)

	@Test
	fun `owner deletes item and compacts later visit orders in ascending order`() {
		val travel = travel(mockUser(OWNER_ID))
		val deletedItem = item(travel, ITEM_ID, 2)
		val thirdItem = item(travel, THIRD_ITEM_ID, 3)
		val fourthItem = item(travel, FOURTH_ITEM_ID, 4)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(deletedItem)
		`when`(timelineItemRepository.findItemsAfterVisitOrder(TRAVEL_ID, 1, 2))
			.thenReturn(listOf(thirdItem, fourthItem))

		service.deleteTimelineItem(TRAVEL_ID, ITEM_ID, OWNER_ID)

		assertEquals(2, thirdItem.visitOrder.toInt())
		assertEquals(3, fourthItem.visitOrder.toInt())
		val persistenceOrder = inOrder(timelineItemRepository)
		persistenceOrder.verify(timelineItemRepository).delete(deletedItem)
		persistenceOrder.verify(timelineItemRepository).flush()
		persistenceOrder.verify(timelineItemRepository).saveAndFlush(thirdItem)
		persistenceOrder.verify(timelineItemRepository).saveAndFlush(fourthItem)
		verifyNoInteractions(travelMemberRepository)
	}

	@Test
	fun `accepted read write member can delete item`() {
		val travel = travel(mockUser(OWNER_ID))
		val item = item(travel, ITEM_ID, 1)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID)).thenReturn(true)
		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(item)
		`when`(timelineItemRepository.findItemsAfterVisitOrder(TRAVEL_ID, 1, 1)).thenReturn(emptyList())

		service.deleteTimelineItem(TRAVEL_ID, ITEM_ID, MEMBER_ID)

		verify(timelineItemRepository).delete(item)
		verify(timelineItemRepository).flush()
	}

	@Test
	fun `read only member and item from another travel are rejected before deletion`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.existsAcceptedReadWriteMember(TRAVEL_ID, MEMBER_ID)).thenReturn(false)
		assertThrows<TimelineItemDeleteAccessDeniedException> {
			service.deleteTimelineItem(TRAVEL_ID, ITEM_ID, MEMBER_ID)
		}

		`when`(timelineItemRepository.findByIdAndTravelId(ITEM_ID, TRAVEL_ID)).thenReturn(null)
		assertThrows<TimelineDeleteItemNotFoundException> {
			service.deleteTimelineItem(TRAVEL_ID, ITEM_ID, OWNER_ID)
		}
		verify(timelineItemRepository, never()).delete(org.mockito.ArgumentMatchers.any())
	}

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = Travel(
		id = TRAVEL_ID,
		owner = owner,
		title = "타임라인 삭제 여행",
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
		name = "삭제 테스트 일정",
		visitOrder = visitOrder,
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000024")
		private val ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000124")
		private val THIRD_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000224")
		private val FOURTH_ITEM_ID = UUID.fromString("00000000-0000-0000-0000-000000000324")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
	}
}
