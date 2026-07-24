package com.ktcloud.travelplanner.user.service
import com.ktcloud.travelplanner.auth.service.RefreshTokenService
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.verifyNoMoreInteractions
import org.mockito.Mockito.`when`
import java.util.Optional
import java.util.UUID
import kotlin.test.assertEquals
import kotlin.test.assertTrue
class UserAccountServiceTest {
        private val userRepository = mock(UserRepository::class.java)
        private val refreshTokenService = mock(RefreshTokenService::class.java)
        private val travelRepository = mock(TravelRepository::class.java)
        private val travelMemberRepository = mock(TravelMemberRepository::class.java)
        private val service = UserAccountService(
                userRepository,
                refreshTokenService,
                travelRepository,
                travelMemberRepository,
                TestFixtures.FIXED_CLOCK,
        )

        @Test
        fun `soft deletes user and revokes refresh token`() {
                val user = User(OAuthProvider.GOOGLE, "account-to-delete")
                `when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))
                `when`(userRepository.saveAndFlush(user)).thenReturn(user)
                `when`(travelRepository.findAllByOwnerId(TestFixtures.USER_ID)).thenReturn(emptyList())

                service.deleteAccount(TestFixtures.USER_ID, REFRESH_TOKEN)

                assertTrue(user.isDeleted)
                assertEquals(TestFixtures.FIXED_INSTANT, user.deletedAt)
                verify(userRepository).saveAndFlush(user)
                verify(refreshTokenService).revoke(REFRESH_TOKEN)
        }

        @Test
        fun `rejects repeated transition when active user no longer exists`() {
                `when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.empty())
                assertThrows<UserNotFoundException> {
                        service.deleteAccount(TestFixtures.USER_ID, REFRESH_TOKEN)
                }
                verifyNoInteractions(refreshTokenService)
                verifyNoInteractions(travelRepository)
        }

        // 이슈 #150 — 소유권 이전 후보가 있으면 이전하고, 이전받은 멤버 행은 삭제한다
        @Test
        fun `transfers ownership to candidate when an owned travel has an accepted member`() {
                val user = User(OAuthProvider.GOOGLE, "owner-to-delete")
                `when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))
                `when`(userRepository.saveAndFlush(user)).thenReturn(user)

                val travelId = UUID.fromString("00000000-0000-0000-0000-000000000030")
                val travel = mock(Travel::class.java)
                `when`(travel.id).thenReturn(travelId)
                `when`(travelRepository.findAllByOwnerId(TestFixtures.USER_ID)).thenReturn(listOf(travel))

                val candidateUser = mock(User::class.java)
                val candidateMember = mock(TravelMember::class.java)
                `when`(candidateMember.user).thenReturn(candidateUser)
                `when`(travelMemberRepository.findOwnershipTransferCandidates(travelId))
                        .thenReturn(listOf(candidateMember))

                service.deleteAccount(TestFixtures.USER_ID, REFRESH_TOKEN)

                verify(travel).transferOwnership(candidateUser)
                verify(travelMemberRepository).delete(candidateMember)
        }

        // 이슈 #150 — 후보가 없으면(멤버 없음) 소유권을 건드리지 않고 그대로 둔다
        // travelMemberRepository에 조회(findOwnershipTransferCandidates) 외에 다른 상호작용이
        // 없다는 것으로 "이전 로직이 실행되지 않았다"를 검증한다 (delete가 호출되지 않았다는 뜻)
        @Test
        fun `leaves ownership untouched when an owned travel has no accepted member`() {
                val user = User(OAuthProvider.GOOGLE, "lonely-owner-to-delete")
                `when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))
                `when`(userRepository.saveAndFlush(user)).thenReturn(user)

                val travelId = UUID.fromString("00000000-0000-0000-0000-000000000031")
                val travel = mock(Travel::class.java)
                `when`(travel.id).thenReturn(travelId)
                `when`(travelRepository.findAllByOwnerId(TestFixtures.USER_ID)).thenReturn(listOf(travel))
                `when`(travelMemberRepository.findOwnershipTransferCandidates(travelId)).thenReturn(emptyList())

                service.deleteAccount(TestFixtures.USER_ID, REFRESH_TOKEN)

                verify(travelMemberRepository).findOwnershipTransferCandidates(travelId)
                verifyNoMoreInteractions(travelMemberRepository)
        }

        // 이슈 #150 — 여러 플랜을 소유하고 있으면, 플랜마다 독립적으로 판단한다
        @Test
        fun `handles multiple owned travels independently`() {
                val user = User(OAuthProvider.GOOGLE, "multi-owner-to-delete")
                `when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))
                `when`(userRepository.saveAndFlush(user)).thenReturn(user)

                val travelWithMemberId = UUID.fromString("00000000-0000-0000-0000-000000000032")
                val travelWithMember = mock(Travel::class.java)
                `when`(travelWithMember.id).thenReturn(travelWithMemberId)

                val travelWithoutMemberId = UUID.fromString("00000000-0000-0000-0000-000000000033")
                val travelWithoutMember = mock(Travel::class.java)
                `when`(travelWithoutMember.id).thenReturn(travelWithoutMemberId)

                `when`(travelRepository.findAllByOwnerId(TestFixtures.USER_ID))
                        .thenReturn(listOf(travelWithMember, travelWithoutMember))

                val candidateUser = mock(User::class.java)
                val candidateMember = mock(TravelMember::class.java)
                `when`(candidateMember.user).thenReturn(candidateUser)
                `when`(travelMemberRepository.findOwnershipTransferCandidates(travelWithMemberId))
                        .thenReturn(listOf(candidateMember))
                `when`(travelMemberRepository.findOwnershipTransferCandidates(travelWithoutMemberId))
                        .thenReturn(emptyList())

                service.deleteAccount(TestFixtures.USER_ID, REFRESH_TOKEN)

                verify(travelWithMember).transferOwnership(candidateUser)
                verify(travelMemberRepository).delete(candidateMember)
        }

        companion object {
                private val REFRESH_TOKEN = "r".repeat(43)
        }
}
