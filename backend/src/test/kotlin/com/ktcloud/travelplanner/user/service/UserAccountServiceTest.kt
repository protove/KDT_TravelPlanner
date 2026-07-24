package com.ktcloud.travelplanner.user.service
import com.ktcloud.travelplanner.auth.service.RefreshTokenService
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.verify
import org.mockito.Mockito.verifyNoInteractions
import org.mockito.Mockito.`when`
import java.util.Optional
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
        companion object {
                private val REFRESH_TOKEN = "r".repeat(43)
        }
}
