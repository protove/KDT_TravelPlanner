package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import com.ktcloud.travelplanner.user.service.NicknameGenerator
import org.junit.jupiter.api.Test
import org.mockito.ArgumentMatchers.any
import org.mockito.Mockito.mock
import org.mockito.Mockito.`when`
import kotlin.test.assertEquals

class OAuthNewUserRegistrarTest {
	private val userRepository = mock(UserRepository::class.java)
	private val nicknameGenerator = mock(NicknameGenerator::class.java)
	private val registrar = OAuthNewUserRegistrar(userRepository, nicknameGenerator)

	@Test
	fun `registers a new user with a generated nickname`() {
		val profile = OAuthUserProfile(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "google-user",
			email = "user@example.com",
			name = "Google User",
			profileImageUrl = "https://images.example/profile.png",
		)
		`when`(nicknameGenerator.generate()).thenReturn("여행러111111")
		`when`(userRepository.saveAndFlush(any(User::class.java))).thenAnswer { it.getArgument(0) }

		val user = registrar.register(profile)

		assertEquals(OAuthProvider.GOOGLE, user.provider)
		assertEquals("google-user", user.providerUserId)
		assertEquals("user@example.com", user.email)
		assertEquals("Google User", user.name)
		assertEquals("https://images.example/profile.png", user.profileImageUrl)
		assertEquals("여행러111111", user.nickname)
	}
}
