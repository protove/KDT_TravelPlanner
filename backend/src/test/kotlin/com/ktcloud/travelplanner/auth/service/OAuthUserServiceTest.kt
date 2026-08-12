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
	private val newUserRegistrar = mock(OAuthNewUserRegistrar::class.java)
	private val service = OAuthUserService(userRepository, newUserRegistrar)

	@Test
	fun `creates a new user from Google profile`() {
		val profile = profile()
		val registeredUser = User(
			provider = OAuthProvider.GOOGLE,
			providerUserId = "google-user",
			email = profile.email,
			name = profile.name,
		).also {
			it.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			it.assignGeneratedNickname("여행러123456")
		}
		`when`(
			userRepository.findByProviderAndProviderUserId(
				OAuthProvider.GOOGLE,
				"google-user",
			),
		).thenReturn(null)
		// 신규 유저 저장은 이제 userRepository.save()가 아니라 newUserRegistrar.register()를
		// 거치므로(동시가입 재시도를 위해 독립 트랜잭션으로 분리됨), 그쪽을 스텁한다.
		`when`(newUserRegistrar.register(profile)).thenReturn(registeredUser)

		val user = service.upsert(profile)

		assertEquals(OAuthProvider.GOOGLE, user.provider)
		assertEquals("google-user", user.providerUserId)
		assertEquals("user@example.com", user.email)
		assertEquals("Google User", user.name)
		assertEquals("https://images.example/profile.png", user.profileImageUrl)
		assertEquals("여행러123456", user.nickname)
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
