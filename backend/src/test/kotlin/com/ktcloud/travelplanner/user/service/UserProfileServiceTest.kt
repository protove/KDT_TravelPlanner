package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.testsupport.TestFixtures
import com.ktcloud.travelplanner.user.model.Gender
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import java.util.Optional
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

class UserProfileServiceTest {
	private val userRepository = mock(UserRepository::class.java)
	private val service = UserProfileService(userRepository)

	@Test
	fun `maps persisted user to profile response`() {
		val user = mockUser(
			email = "profile@example.com",
			name = "Profile User",
			nickname = "traveler",
			profileImageUrl = "https://images.example/profile.png",
			gender = Gender.UNSPECIFIED,
			birthYear = 2001,
			isProfileCompleted = true,
		)
		`when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))

		val response = service.getProfile(TestFixtures.USER_ID)

		assertEquals(TestFixtures.USER_ID, response.userId)
		assertEquals(OAuthProvider.GOOGLE, response.provider)
		assertEquals("profile@example.com", response.email)
		assertEquals("Profile User", response.name)
		assertEquals("traveler", response.nickname)
		assertEquals("https://images.example/profile.png", response.profileImageUrl)
		assertEquals(Gender.UNSPECIFIED, response.gender)
		assertEquals(2001, response.birthYear)
		assertEquals(true, response.isProfileCompleted)
	}

	@Test
	fun `preserves nullable profile fields`() {
		val user = mockUser()
		`when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.of(user))

		val response = service.getProfile(TestFixtures.USER_ID)

		assertNull(response.email)
		assertNull(response.name)
		assertNull(response.nickname)
		assertNull(response.profileImageUrl)
		assertNull(response.gender)
		assertNull(response.birthYear)
		assertFalse(response.isProfileCompleted)
	}

	@Test
	fun `rejects absent user`() {
		`when`(userRepository.findById(TestFixtures.USER_ID)).thenReturn(Optional.empty())

		assertThrows<UserNotFoundException> {
			service.getProfile(TestFixtures.USER_ID)
		}
	}

	private fun mockUser(
		email: String? = null,
		name: String? = null,
		nickname: String? = null,
		profileImageUrl: String? = null,
		gender: Gender? = null,
		birthYear: Int? = null,
		isProfileCompleted: Boolean = false,
	): User = mock(User::class.java).also { user ->
		`when`(user.id).thenReturn(TestFixtures.USER_ID)
		`when`(user.provider).thenReturn(OAuthProvider.GOOGLE)
		`when`(user.email).thenReturn(email)
		`when`(user.name).thenReturn(name)
		`when`(user.nickname).thenReturn(nickname)
		`when`(user.profileImageUrl).thenReturn(profileImageUrl)
		`when`(user.gender).thenReturn(gender)
		`when`(user.birthYear).thenReturn(birthYear?.toShort())
		`when`(user.isProfileCompleted).thenReturn(isProfileCompleted)
	}
}
