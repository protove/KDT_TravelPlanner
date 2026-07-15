package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateRequest
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertSame

class TravelInvitationServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val userRepository = mock(UserRepository::class.java)
	private val service = TravelInvitationService(
		travelRepository,
		travelMemberRepository,
		userRepository,
		TestFixtures.FIXED_CLOCK,
	)

	@Test
	fun `owner creates pending invitation for nickname with requested role`() {
		val owner = mockUser(OWNER_ID)
		val invitee = mockUser(INVITEE_ID)
		val travel = travel(owner)
		lateinit var savedMember: TravelMember
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(userRepository.findByNickname("invitee")).thenReturn(invitee)
		`when`(travelMemberRepository.existsByTravelAndUser(TRAVEL_ID, INVITEE_ID)).thenReturn(false)
		`when`(travelMemberRepository.save(any(TravelMember::class.java))).thenAnswer {
			it.getArgument<TravelMember>(0).also { member -> savedMember = member }
		}

		val response = service.createInvitation(TRAVEL_ID, OWNER_ID, request())

		assertEquals(savedMember.id, response.invitationId)
		assertSame(travel, savedMember.travel)
		assertSame(invitee, savedMember.user)
		assertEquals(TravelRole.READ_WRITE, savedMember.role)
		assertEquals(TestFixtures.FIXED_INSTANT, savedMember.invitedAt)
	}

	@Test
	fun `non owner cannot resolve target or create invitation`() {
		val travel = travel(mockUser(OWNER_ID))
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))

		assertThrows<InvitationAccessDeniedException> {
			service.createInvitation(TRAVEL_ID, INVITEE_ID, request())
		}

		verifyNoInteractions(userRepository, travelMemberRepository)
	}

	@Test
	fun `owner cannot invite self or existing membership`() {
		val owner = mockUser(OWNER_ID)
		val travel = travel(owner)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(userRepository.findByNickname("invitee")).thenReturn(owner)

		assertThrows<SelfInvitationException> {
			service.createInvitation(TRAVEL_ID, OWNER_ID, request())
		}

		val invitee = mockUser(INVITEE_ID)
		`when`(userRepository.findByNickname("invitee")).thenReturn(invitee)
		`when`(travelMemberRepository.existsByTravelAndUser(TRAVEL_ID, INVITEE_ID)).thenReturn(true)

		assertThrows<DuplicateInvitationException> {
			service.createInvitation(TRAVEL_ID, OWNER_ID, request())
		}

		verify(travelMemberRepository, never()).save(any(TravelMember::class.java))
	}

	private fun request() = TravelInvitationCreateRequest("invitee", TravelRole.READ_WRITE)

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
	}

	private fun travel(owner: User): Travel = Travel(
		id = TRAVEL_ID,
		owner = owner,
		title = "초대 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-02"),
	)

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000028")
		private val OWNER_ID = TestFixtures.USER_ID
		private val INVITEE_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
	}
}
