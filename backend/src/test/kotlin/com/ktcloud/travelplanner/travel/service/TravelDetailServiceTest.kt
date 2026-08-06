package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.PlannerPurposeRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.Instant
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TravelDetailServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val plannerPurposeRepository = mock(PlannerPurposeRepository::class.java)
	private val service = TravelDetailService(
		travelRepository,
		travelMemberRepository,
		timelineItemRepository,
		plannerPurposeRepository,
	)

	@Test
	fun `owner receives assembled detail with timeline`() {
		val travel = travel(mockUser(OWNER_ID))
		val timelineItem = TimelineItem(
			travel = travel,
			dayNumber = 1,
			visitDate = LocalDate.parse("2026-08-01"),
			category = TimelineCategory.ATTRACTION,
			name = "도쿄 타워",
			visitOrder = 1,
		)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(listOf(timelineItem))
		`when`(plannerPurposeRepository.findAllByTravelId(TRAVEL_ID)).thenReturn(emptyList())

		val response = service.getTravelDetail(TRAVEL_ID, OWNER_ID)

		assertEquals(TravelPermission.OWNER, response.permission)
		assertEquals("상세 여행", response.title)
		assertEquals(3, response.travelDays)
		assertEquals("도쿄 타워", response.timelineItems.single().name)
		verifyNoInteractions(travelMemberRepository)
	}

	@Test
	fun `accepted participants receive their current permission`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(emptyList())
		`when`(plannerPurposeRepository.findAllByTravelId(TRAVEL_ID)).thenReturn(emptyList())
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID))
			.thenReturn(TravelRole.READ_ONLY)

		val response = service.getTravelDetail(TRAVEL_ID, MEMBER_ID)

		assertEquals(TravelPermission.READ_ONLY, response.permission)
	}

	@Test
	fun `missing travel and non participant are rejected before timeline lookup`() {
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.empty())
		assertThrows<TravelDetailNotFoundException> {
			service.getTravelDetail(TRAVEL_ID, MEMBER_ID)
		}

		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID)).thenReturn(null)
		assertThrows<TravelDetailAccessDeniedException> {
			service.getTravelDetail(TRAVEL_ID, MEMBER_ID)
		}
		verifyNoInteractions(timelineItemRepository)
	}

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = mock(Travel::class.java).also {
		`when`(it.id).thenReturn(TRAVEL_ID)
		`when`(it.owner).thenReturn(owner)
		`when`(it.title).thenReturn("상세 여행")
		`when`(it.startDate).thenReturn(LocalDate.parse("2026-08-01"))
		`when`(it.endDate).thenReturn(LocalDate.parse("2026-08-03"))
		`when`(it.travelDays).thenReturn(3)
		`when`(it.country).thenReturn(null)
		`when`(it.city).thenReturn(null)
		`when`(it.companionType).thenReturn(null)
		`when`(it.participantCount).thenReturn(null)
		`when`(it.comment).thenReturn("상세 코멘트")
		`when`(it.version).thenReturn(0)
		`when`(it.createdAt).thenReturn(CREATED_AT)
		`when`(it.updatedAt).thenReturn(UPDATED_AT)
	}

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000019")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
		private val CREATED_AT = Instant.parse("2026-01-01T00:00:00Z")
		private val UPDATED_AT = Instant.parse("2026-01-02T00:00:00Z")
	}
}
