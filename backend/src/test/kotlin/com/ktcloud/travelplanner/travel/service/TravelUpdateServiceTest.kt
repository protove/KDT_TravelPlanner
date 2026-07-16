package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.dto.TravelUpdateRequest
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.dto.PatchField
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import org.springframework.dao.OptimisticLockingFailureException
import java.time.Instant
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TravelUpdateServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val countryRepository = mock(CountryRepository::class.java)
	private val cityRepository = mock(CityRepository::class.java)
	private val timelineItemRepository = mock(TimelineItemRepository::class.java)
	private val service = TravelUpdateService(
		travelRepository,
		travelMemberRepository,
		countryRepository,
		cityRepository,
		timelineItemRepository,
	)

	@Test
	fun `owner applies partial update while absent fields keep current values`() {
		val owner = mockUser(OWNER_ID)
		val travel = travel(owner)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(emptyList())
		`when`(travelRepository.saveAndFlush(travel)).thenReturn(travel)

		val response = service.updateTravel(
			TRAVEL_ID,
			OWNER_ID,
			TravelUpdateRequest(title = PatchField.Present(" 수정 후 여행 "), version = 2),
		)

		assertEquals("수정 전 여행", response.title)
		verify(travel).updateBasicInfo(
			"수정 후 여행",
			START_DATE,
			END_DATE,
			null,
			null,
			null,
			null,
			"기존 코멘트",
		)
		verifyNoInteractions(travelMemberRepository, countryRepository, cityRepository)
	}

	@Test
	fun `only accepted read write participant can update`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, MEMBER_ID)).thenReturn(TravelRole.READ_WRITE)
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(emptyList())
		`when`(travelRepository.saveAndFlush(travel)).thenReturn(travel)

		service.updateTravel(TRAVEL_ID, MEMBER_ID, TravelUpdateRequest(version = 2))

		`when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, READ_ONLY_ID)).thenReturn(TravelRole.READ_ONLY)
		assertThrows<TravelUpdateAccessDeniedException> {
			service.updateTravel(TRAVEL_ID, READ_ONLY_ID, TravelUpdateRequest(version = 2))
		}
	}

	@Test
	fun `stale version and incompatible timeline dates are conflicts`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		assertThrows<TravelVersionConflictException> {
			service.updateTravel(TRAVEL_ID, OWNER_ID, TravelUpdateRequest(version = 1))
		}
		verifyNoInteractions(timelineItemRepository)

		val timelineItem = mock(TimelineItem::class.java)
		`when`(timelineItem.visitDate).thenReturn(LocalDate.parse("2026-08-03"))
		`when`(timelineItem.dayNumber).thenReturn(3)
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(listOf(timelineItem))
		assertThrows<TravelTimelineDateConflictException> {
			service.updateTravel(
				TRAVEL_ID,
				OWNER_ID,
				TravelUpdateRequest(startDate = PatchField.Present(LocalDate.parse("2026-08-02")), version = 2),
			)
		}
		verify(travelRepository, never()).saveAndFlush(travel)
	}

	@Test
	fun `concurrent jpa update is mapped to version conflict`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(TRAVEL_ID))
			.thenReturn(emptyList())
		`when`(travelRepository.saveAndFlush(travel)).thenThrow(OptimisticLockingFailureException("stale"))

		assertThrows<TravelVersionConflictException> {
			service.updateTravel(TRAVEL_ID, OWNER_ID, TravelUpdateRequest(version = 2))
		}
	}

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = mock(Travel::class.java).also {
		`when`(it.id).thenReturn(TRAVEL_ID)
		`when`(it.owner).thenReturn(owner)
		`when`(it.title).thenReturn("수정 전 여행")
		`when`(it.startDate).thenReturn(START_DATE)
		`when`(it.endDate).thenReturn(END_DATE)
		`when`(it.country).thenReturn(null)
		`when`(it.city).thenReturn(null)
		`when`(it.companionType).thenReturn(null)
		`when`(it.participantCount).thenReturn(null)
		`when`(it.comment).thenReturn("기존 코멘트")
		`when`(it.version).thenReturn(2)
		`when`(it.travelDays).thenReturn(3)
		`when`(it.createdAt).thenReturn(CREATED_AT)
		`when`(it.updatedAt).thenReturn(UPDATED_AT)
	}

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000020")
		private val OWNER_ID = TestFixtures.USER_ID
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
		private val READ_ONLY_ID = UUID.fromString("00000000-0000-0000-0000-000000000003")
		private val START_DATE = LocalDate.parse("2026-08-01")
		private val END_DATE = LocalDate.parse("2026-08-03")
		private val CREATED_AT = Instant.parse("2026-01-01T00:00:00Z")
		private val UPDATED_AT = Instant.parse("2026-01-02T00:00:00Z")
	}
}
