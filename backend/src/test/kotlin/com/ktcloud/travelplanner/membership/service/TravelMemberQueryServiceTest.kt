package com.ktcloud.travelplanner.membership.service
import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import java.time.Instant
import java.time.LocalDate
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
class TravelMemberQueryServiceTest {
        private val travelRepository = mock(TravelRepository::class.java)
        private val travelMemberRepository = mock(TravelMemberRepository::class.java)
        private val userRepository = mock(UserRepository::class.java)
        private val service = TravelMemberQueryService(travelRepository, travelMemberRepository, userRepository)
        @Test
        fun `owner and accepted members are combined with owner first`() {
                val owner = mockUser(OWNER_ID, "owner")
                val travel = travel(owner)
                val readOnlyMember = acceptedMember(travel, mockUser(READ_ONLY_ID, "reader"), TravelRole.READ_ONLY)
                val readWriteMember = acceptedMember(travel, mockUser(READ_WRITE_ID, "writer"), TravelRole.READ_WRITE)
                `when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
                `when`(travelMemberRepository.findAcceptedMembers(TRAVEL_ID))
                        .thenReturn(listOf(readOnlyMember, readWriteMember))
                val response = service.getTravelMembers(TRAVEL_ID, OWNER_ID)
                assertEquals(listOf(OWNER_ID, READ_ONLY_ID, READ_WRITE_ID), response.map { it.userId })
                assertEquals(TravelPermission.OWNER, response[0].role)
                assertTrue(response[0].isOwner)
                assertEquals(TravelPermission.READ_ONLY, response[1].role)
                assertFalse(response[1].isOwner)
                assertEquals(TravelPermission.READ_WRITE, response[2].role)
                verify(travelMemberRepository, never()).findAcceptedRole(TRAVEL_ID, OWNER_ID)
        }
        @Test
        fun `accepted read only or read write member can query list`() {
                val travel = travel(mockUser(OWNER_ID, "owner"))
                `when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
                `when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, READ_ONLY_ID)).thenReturn(TravelRole.READ_ONLY)
                `when`(travelMemberRepository.findAcceptedMembers(TRAVEL_ID)).thenReturn(emptyList())
                val response = service.getTravelMembers(TRAVEL_ID, READ_ONLY_ID)
                assertEquals(1, response.size)
                verify(travelMemberRepository).findAcceptedMembers(TRAVEL_ID)
        }
        @Test
        fun `user without accepted membership cannot query list`() {
                val travel = travel(mockUser(OWNER_ID, "owner"))
                `when`(travelRepository.findById(TRAVEL_ID)).thenReturn(Optional.of(travel))
                `when`(travelMemberRepository.findAcceptedRole(TRAVEL_ID, OUTSIDER_ID)).thenReturn(null)
                assertThrows<TravelMemberAccessDeniedException> {
                        service.getTravelMembers(TRAVEL_ID, OUTSIDER_ID)
                }
                verify(travelMemberRepository, never()).findAcceptedMembers(TRAVEL_ID)
        }

        private fun acceptedMember(
                travel: Travel,
                user: User,
                role: TravelRole,
        ): TravelMember = TravelMember(
                travel = travel,
                user = user,
                role = role,
                invitedAt = INVITED_AT,
        ).also {
                it.respond(TravelInvitationAction.ACCEPT, INVITED_AT.plusSeconds(1))
        }
        private fun mockUser(
                id: UUID,
                nickname: String,
        ): User = mock(User::class.java).also {
                `when`(it.id).thenReturn(id)
                `when`(it.nickname).thenReturn(nickname)
        }
        private fun travel(owner: User): Travel = Travel(
                id = TRAVEL_ID,
                owner = owner,
                title = "참여자 여행",
                startDate = LocalDate.parse("2026-08-01"),
                endDate = LocalDate.parse("2026-08-02"),
        )
        companion object {
                private val TRAVEL_ID = UUID.fromString("00000000-0000-0000-0000-000000000032")
                private val OWNER_ID = UUID.fromString("00000000-0000-0000-0000-000000000001")
                private val READ_ONLY_ID = UUID.fromString("00000000-0000-0000-0000-000000000002")
                private val READ_WRITE_ID = UUID.fromString("00000000-0000-0000-0000-000000000003")
                private val OUTSIDER_ID = UUID.fromString("00000000-0000-0000-0000-000000000004")
                private val INVITED_AT = Instant.parse("2026-07-01T00:00:00Z")
        }
}
