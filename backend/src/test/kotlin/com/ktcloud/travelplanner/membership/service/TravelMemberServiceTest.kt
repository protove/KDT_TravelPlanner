package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.membership.dto.TravelMemberRoleUpdateRequest
import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import java.time.Instant
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals

class TravelMemberServiceTest {
	private val travelRepository = mock(TravelRepository::class.java)
	private val travelMemberRepository = mock(TravelMemberRepository::class.java)
	private val service = TravelMemberService(travelRepository, travelMemberRepository)

	@Test
	fun `accepted member leaves travel`() {
		val travel = travel()
		val member = acceptedMember(travel)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(member))

		service.leaveTravel(TRAVEL_ID, MEMBER_ID)

		verify(travelMemberRepository).delete(member)
	}

	@Test
	fun `owner and non member cannot leave travel`() {
		val travel = travel()
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.empty())

		assertThrows<TravelOwnerLeaveException> {
			service.leaveTravel(TRAVEL_ID, OWNER_ID)
		}
		assertThrows<TravelMemberNotFoundException> {
			service.leaveTravel(TRAVEL_ID, MEMBER_ID)
		}

		verify(travelMemberRepository, never()).delete(any(TravelMember::class.java))
	}

	@Test
	fun `pending member cannot leave travel`() {
		val travel = travel()
		val pendingMember = TravelMember(
			travel = travel,
			user = mockUser(MEMBER_ID),
			role = TravelRole.READ_ONLY,
			invitedAt = INVITED_AT,
		)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(pendingMember))

		assertThrows<PendingTravelMemberLeaveException> {
			service.leaveTravel(TRAVEL_ID, MEMBER_ID)
		}

		verify(travelMemberRepository, never()).delete(pendingMember)
	}

	@Test
	fun `owner removes accepted member`() {
		val travel = travel()
		val member = acceptedMember(travel)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(member))

		service.removeMember(TRAVEL_ID, MEMBER_ID, OWNER_ID)

		verify(travelMemberRepository).delete(member)
	}

	@Test
	fun `non owner owner target and pending member cannot be removed`() {
		val travel = travel()
		val pendingMember = TravelMember(
			travel = travel,
			user = mockUser(MEMBER_ID),
			role = TravelRole.READ_ONLY,
			invitedAt = INVITED_AT,
		)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(pendingMember))

		assertThrows<TravelMemberAccessDeniedException> {
			service.removeMember(TRAVEL_ID, MEMBER_ID, MEMBER_ID)
		}
		assertThrows<TravelOwnerRemovalException> {
			service.removeMember(TRAVEL_ID, OWNER_ID, OWNER_ID)
		}
		assertThrows<PendingTravelMemberRemovalException> {
			service.removeMember(TRAVEL_ID, MEMBER_ID, OWNER_ID)
		}

		verify(travelMemberRepository, never()).delete(pendingMember)
	}

	@Test
	fun `owner changes accepted member role`() {
		val travel = travel()
		val member = acceptedMember(travel)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(member))
		`when`(travelMemberRepository.save(member)).thenReturn(member)

		val response = service.updateMemberRole(
			TRAVEL_ID,
			MEMBER_ID,
			OWNER_ID,
			TravelMemberRoleUpdateRequest(TravelRole.READ_WRITE),
		)

		assertEquals(TravelRole.READ_WRITE, member.role)
		assertEquals(TravelPermission.READ_WRITE, response.role)
	}

	@Test
	fun `non owner and owner target cannot change role`() {
		val travel = travel()
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))

		assertThrows<TravelMemberAccessDeniedException> {
			service.updateMemberRole(
				TRAVEL_ID,
				MEMBER_ID,
				MEMBER_ID,
				TravelMemberRoleUpdateRequest(TravelRole.READ_ONLY),
			)
		}
		assertThrows<TravelOwnerRoleUpdateException> {
			service.updateMemberRole(
				TRAVEL_ID,
				OWNER_ID,
				OWNER_ID,
				TravelMemberRoleUpdateRequest(TravelRole.READ_ONLY),
			)
		}

		verify(travelMemberRepository, never()).save(any(TravelMember::class.java))
	}

	@Test
	fun `pending member role cannot be changed`() {
		val travel = travel()
		val pendingMember = TravelMember(
			travel = travel,
			user = mockUser(MEMBER_ID),
			role = TravelRole.READ_ONLY,
			invitedAt = INVITED_AT,
		)
		`when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
		`when`(travelMemberRepository.findByTravelAndUserForUpdate(TRAVEL_ID, MEMBER_ID))
			.thenReturn(Optional.of(pendingMember))

		assertThrows<PendingTravelMemberRoleUpdateException> {
			service.updateMemberRole(
				TRAVEL_ID,
				MEMBER_ID,
				OWNER_ID,
				TravelMemberRoleUpdateRequest(TravelRole.READ_WRITE),
			)
		}

		verify(travelMemberRepository, never()).save(pendingMember)
	}

	private fun acceptedMember(travel: Travel): TravelMember = TravelMember(
		travel = travel,
		user = mockUser(MEMBER_ID),
		role = TravelRole.READ_ONLY,
		invitedAt = INVITED_AT,
	).also {
		it.respond(TravelInvitationAction.ACCEPT, INVITED_AT.plusSeconds(1))
	}

	private fun travel(): Travel = Travel(
		id = TRAVEL_ID,
		owner = mockUser(OWNER_ID),
		title = "권한 변경 여행",
		startDate = LocalDate.parse("2026-08-01"),
		endDate = LocalDate.parse("2026-08-02"),
	)

	private fun mockUser(id: UUID): User = mock(User::class.java).also {
		`when`(it.id).thenReturn(id)
		`when`(it.nickname).thenReturn("member")
	}

	companion object {
		private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000033")
		private val OWNER_ID = UUID.fromString("00000000-0000-0000-0000-000000000001")
		private val MEMBER_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
		private val INVITED_AT = Instant.parse("2026-07-01T00:00:00Z")
	}
}
