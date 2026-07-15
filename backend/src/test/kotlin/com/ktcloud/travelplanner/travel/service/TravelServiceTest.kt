package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.travel.dto.TravelCreateRequest
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelListRow
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import org.springframework.data.domain.PageImpl
import org.springframework.data.domain.PageRequest
import java.time.Instant
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertSame

class TravelServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val service = TravelService(travelRepository, userRepository)

	@Test
	fun `uses authenticated user as owner and returns generated travel id`() {
		val ownerId = UUID.randomUUID()
		val owner = User(OAuthProvider.GOOGLE, "service-owner")
		lateinit var savedTravel: Travel
		`when`(userRepository.findById(ownerId)).thenReturn(Optional.of(owner))
		`when`(travelRepository.save(any(Travel::class.java))).thenAnswer {
			it.getArgument<Travel>(0).also { travel -> savedTravel = travel }
		}

		val response = service.createTravel(ownerId, request())

		assertEquals(savedTravel.id, response.travelId)
		assertSame(owner, savedTravel.owner)
		assertEquals("도쿄 여행", savedTravel.title)
		assertEquals(4, savedTravel.travelDays)
	}

	@Test
	fun `rejects missing authenticated owner before saving`() {
		val ownerId = UUID.randomUUID()
		`when`(userRepository.findById(ownerId)).thenReturn(Optional.empty())

		assertThrows<TravelOwnerNotFoundException> {
			service.createTravel(ownerId, request())
		}

		verifyNoInteractions(travelRepository)
	}

	@Test
	fun `normalizes keyword and maps owner and member permissions into page response`() {
		val userId = UUID.randomUUID()
		val pageable = PageRequest.of(1, 2)
		val rows = listOf(
			row(title = "도쿄 소유 여행", memberRole = null),
			row(title = "도쿄 공유 여행", memberRole = TravelRole.READ_ONLY),
		)
		`when`(travelRepository.findAccessibleTravels(userId, "도쿄", pageable))
			.thenReturn(PageImpl(rows, pageable, 5))

		val response = service.getTravels(userId, "  도쿄  ", 1, 2)

		assertEquals(1, response.page)
		assertEquals(2, response.size)
		assertEquals(5, response.totalElements)
		assertEquals(3, response.totalPages)
		assertEquals(listOf(TravelPermission.OWNER, TravelPermission.READ_ONLY), response.content.map { it.permission })
		verify(travelRepository).findAccessibleTravels(userId, "도쿄", pageable)
	}

	@Test
	fun `blank keyword is treated as absent search condition`() {
		val userId = UUID.randomUUID()
		val pageable = PageRequest.of(0, 20)
		`when`(travelRepository.findAccessibleTravels(userId, null, pageable))
			.thenReturn(PageImpl(emptyList(), pageable, 0))

		service.getTravels(userId, "  ", 0, 20)

		verify(travelRepository).findAccessibleTravels(userId, null, pageable)
	}

	private fun request(): TravelCreateRequest = TravelCreateRequest(
		title = "도쿄 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-04"),
	)

	private fun row(
		title: String,
		memberRole: TravelRole?,
	): TravelListRow = TravelListRow(
		travelId = UUID.randomUUID(),
		title = title,
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-04"),
		countryId = null,
		cityId = null,
		participantCount = null,
		updatedAt = Instant.parse("2026-01-01T00:00:00Z"),
		memberRole = memberRole,
	)
}
