package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.never
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import kotlin.test.assertEquals
import kotlin.test.assertSame

class OAuthUserServiceTest {
	private val userRepository = mock(UserRepository::class.java)
	private val service = OAuthUserService(userRepository)

	@Test
	fun `creates a new user from Google profile`() {
		val profile = profile()
		`when`(
			userRepository.findByProviderAndProviderUserId(
				OAuthProvider.GOOGLE,
				"google-user",
			),
		).thenReturn(null)
		`when`(userRepository.save(any(User::class.java))).thenAnswer { it.getArgument(0) }

		val user = service.upsert(profile)

		assertEquals(OAuthProvider.GOOGLE, user.provider)
		assertEquals("google-user", user.providerUserId)
		assertEquals("user@example.com", user.email)
		assertEquals("Google User", user.name)
		assertEquals("https://images.example/profile.png", user.profileImageUrl)
	}

	@Test
	fun `updates OAuth fields when the provider user already exists`() {
		val existingUser = User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "google-user",
			email = "old@example.com",
			name = "Old Name",
		)
		`when`(
			userRepository.findByProviderAndProviderUserId(
				OAuthProvider.GOOGLE,
				"google-user",
			),
		).thenReturn(existingUser)

		val user = service.upsert(profile())

		assertSame(existingUser, user)
		assertEquals("user@example.com", user.email)
		assertEquals("Google User", user.name)
		assertEquals("https://images.example/profile.png", user.profileImageUrl)
		verify(userRepository, never()).save(any(User::class.java))
	}

	private fun profile(): OAuthUserProfile = OAuthUserProfile(
		provider = OAuthProvider.GOOGLE,
		providerUserId = "google-user",
		email = "user@example.com",
		name = "Google User",
		profileImageUrl = "https://images.example/profile.png",
	)
}
