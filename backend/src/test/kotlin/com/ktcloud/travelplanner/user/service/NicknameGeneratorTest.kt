package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.user.repository.UserRepository
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.mockito.ArgumentMatchers.anyString
import org.mockito.Mockito.mock
import org.mockito.Mockito.times
import org.mockito.Mockito.verify
import org.mockito.Mockito.`when`
import kotlin.test.assertTrue

class NicknameGeneratorTest {
	private val userRepository = mock(UserRepository::class.java)
	private val generator = NicknameGenerator(userRepository)

	private val nicknamePattern = Regex("^여행러\\d{6}$")

	@Test
	fun `generates a nickname in the 여행러 plus six digit format`() {
		`when`(userRepository.existsByNickname(anyString())).thenReturn(false)

		val nickname = generator.generate()

		assertTrue(nicknamePattern.matches(nickname)) {
			"unexpected nickname format: $nickname"
		}
	}

	@Test
	fun `retries with a new candidate when the nickname is already taken`() {
		// 처음 두 번은 중복, 세 번째부터는 사용 가능하다고 가정
		`when`(userRepository.existsByNickname(anyString())).thenReturn(true, true, false)

		val nickname = generator.generate()

		assertTrue(nicknamePattern.matches(nickname)) {
			"unexpected nickname format: $nickname"
		}
		verify(userRepository, times(3)).existsByNickname(anyString())
	}

	@Test
	fun `gives up after exhausting every retry attempt`() {
		`when`(userRepository.existsByNickname(anyString())).thenReturn(true)

		assertThrows<NicknameGenerationException> {
			generator.generate()
		}
		verify(userRepository, times(MAX_ATTEMPTS)).existsByNickname(anyString())
	}

	companion object {
		private const val MAX_ATTEMPTS = 5
	}
}
