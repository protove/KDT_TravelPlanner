package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Component
import kotlin.random.Random

// SSO 최초 가입 시 부여할 임시 닉네임을 생성한다.
// "여행러" + 숫자 6자리 형태이며, existsByNickname()으로 중복 여부를 확인해
// 이미 사용 중이면 다시 생성한다 (uk_user_table_nickname 유니크 제약과 별개로,
// INSERT 이전에 최대한 충돌을 피하기 위한 선제 체크).
@Component
class NicknameGenerator(
	private val userRepository: UserRepository,
) {
	fun generate(): String {
		repeat(MAX_ATTEMPTS) {
			val candidate = randomCandidate()
			if (!userRepository.existsByNickname(candidate)) {
				return candidate
			}
		}
		throw NicknameGenerationException()
	}

	private fun randomCandidate(): String {
		val digits = Random.nextInt(0, DIGIT_UPPER_BOUND).toString().padStart(DIGIT_LENGTH, '0')
		return "$NICKNAME_PREFIX$digits"
	}

	companion object {
		private const val NICKNAME_PREFIX = "여행러"
		private const val DIGIT_LENGTH = 6
		private const val DIGIT_UPPER_BOUND = 1_000_000
		private const val MAX_ATTEMPTS = 5
	}
}

class NicknameGenerationException : IllegalStateException("닉네임 자동 생성에 실패했습니다.")
