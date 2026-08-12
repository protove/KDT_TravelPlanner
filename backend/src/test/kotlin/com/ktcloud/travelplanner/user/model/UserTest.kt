package com.ktcloud.travelplanner.user.model

import com.ktcloud.travelplanner.testsupport.TestFixtures
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class UserTest {
	@Test
	fun `new OAuth user starts with an incomplete active profile`() {
		val user = createUser()

		assertFalse(user.isProfileCompleted)
		assertFalse(user.isDeleted)
		assertNull(user.nickname)
	}

	@Test
	fun `profile completion stores validated profile state`() {
		val user = createUser()

		user.completeProfile(
			nickname = "travelUser",
			gender = Gender.UNSPECIFIED,
			birthYear = 2001,
		)

		assertTrue(user.isProfileCompleted)
		assertEquals("travelUser", user.nickname)
		assertEquals(Gender.UNSPECIFIED, user.gender)
		assertEquals(2001.toShort(), user.birthYear)
	}

	@Test
	fun `profile completion rejects an invalid birth year`() {
		val user = createUser()

		assertThrows(IllegalArgumentException::class.java) {
			user.completeProfile("travelUser", Gender.OTHER, 1899)
		}
		assertThrows(IllegalArgumentException::class.java) {
			user.completeProfile("travelUser", Gender.OTHER, 2101)
		}
	}

	@Test
	fun `profile completion rejects blank and oversized nicknames`() {
		val user = createUser()

		assertThrows(IllegalArgumentException::class.java) {
			user.completeProfile(" ", Gender.UNSPECIFIED, 2001)
		}
		assertThrows(IllegalArgumentException::class.java) {
			user.completeProfile("a".repeat(31), Gender.UNSPECIFIED, 2001)
		}
	}

	@Test
	fun `profile update supports nullable fields and recalculates completion`() {
		val user = createUser()
		user.completeProfile("travelUser", Gender.OTHER, 2001)

		user.updateProfile(
			nickname = null,
			profileImageUrl = null,
			gender = null,
			birthYear = null,
		)

		assertNull(user.nickname)
		assertNull(user.profileImageUrl)
		assertNull(user.gender)
		assertNull(user.birthYear)
		assertFalse(user.isProfileCompleted)
	}

	@Test
	fun `assigns a generated nickname without marking the profile as completed`() {
		val user = createUser()

		user.assignGeneratedNickname("여행러123456")

		assertEquals("여행러123456", user.nickname)
		assertFalse(user.isProfileCompleted)
		assertNull(user.gender)
		assertNull(user.birthYear)
	}

	@Test
	fun `assigning a generated nickname rejects blank and oversized values`() {
		val user = createUser()

		assertThrows(IllegalArgumentException::class.java) {
			user.assignGeneratedNickname(" ")
		}
		assertThrows(IllegalArgumentException::class.java) {
			user.assignGeneratedNickname("a".repeat(31))
		}
	}

	@Test
	fun `soft delete records UTC deletion time only once`() {
		val user = createUser()

		user.softDelete(TestFixtures.FIXED_INSTANT)

		assertTrue(user.isDeleted)
		assertEquals(TestFixtures.FIXED_INSTANT, user.deletedAt)
		assertThrows(IllegalArgumentException::class.java) {
			user.softDelete(TestFixtures.FIXED_INSTANT)
		}
	}

	@Test
	fun `OAuth provider user id must not be blank`() {
		assertThrows(IllegalArgumentException::class.java) {
			User(OAuthProvider.GOOGLE, " ")
		}
	}

	private fun createUser(): User = User(
		provider = OAuthProvider.GOOGLE,
		providerUserId = "google-user-1",
		email = "user@example.com",
		name = "Travel User",
	)
}
