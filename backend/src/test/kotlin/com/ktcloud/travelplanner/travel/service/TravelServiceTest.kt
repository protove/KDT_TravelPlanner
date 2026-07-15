package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.travel.dto.TravelCreateRequest
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
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

	private fun request(): TravelCreateRequest = TravelCreateRequest(
		title = "도쿄 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-04"),
	)
}
