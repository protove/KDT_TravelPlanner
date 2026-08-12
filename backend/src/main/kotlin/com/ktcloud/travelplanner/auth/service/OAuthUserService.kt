package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.hibernate.exception.ConstraintViolationException
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class OAuthUserService(
	private val userRepository: UserRepository,
	private val newUserRegistrar: OAuthNewUserRegistrar,
) {
	@Transactional
	fun upsert(profile: OAuthUserProfile): User {
		val existingUser = userRepository.findByProviderAndProviderUserId(
			profile.provider,
			profile.providerUserId,
		)
		if (existingUser != null) {
			existingUser.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			return existingUser
		}

		// 이슈 #237 — 탈퇴한 계정은 @SQLRestriction 때문에 위 조회에서 안 잡힌다.
		// 여기서 먼저 걸러내지 않으면 uk_user_table_provider_user_id 유니크 제약 위반으로
		// 처리되지 않은 예외가 발생해 OAuth 콜백이 500으로 끝나버린다.
		// 같은 provider의 "다른" providerUserId는 이 조건에 걸리지 않으므로 정상 가입된다.
		if (
			userRepository.existsWithdrawnByProviderAndProviderUserId(
				profile.provider.name,
				profile.providerUserId,
			)
		) {
			throw WithdrawnOAuthAccountException()
		}

		return registerNewUserWithRetry(profile)
	}

	// NicknameGenerator가 existsByNickname()으로 미리 체크해도, 체크와 저장 사이의
	// 틈에 동시가입이 겹치면 uk_user_table_nickname 유니크 제약 위반이 날 수 있다.
	// OAuthNewUserRegistrar.register()는 독립 트랜잭션(REQUIRES_NEW)이라, 실패해도
	// 그 트랜잭션만 버리고 새 닉네임으로 깨끗하게 재시도할 수 있다.
	private fun registerNewUserWithRetry(profile: OAuthUserProfile): User {
		repeat(MAX_NICKNAME_RETRY) { attempt ->
			try {
				return newUserRegistrar.register(profile)
			} catch (exception: DataIntegrityViolationException) {
				if (!isNicknameUniqueViolation(exception)) {
					throw exception
				}
				if (attempt == MAX_NICKNAME_RETRY - 1) {
					throw NicknameAssignmentFailedException(exception)
				}
			}
		}
		error("registerNewUserWithRetry: unreachable")
	}

	private fun isNicknameUniqueViolation(exception: DataIntegrityViolationException): Boolean =
		(exception.cause as? ConstraintViolationException)?.constraintName == NICKNAME_UNIQUE_CONSTRAINT

	companion object {
		private const val MAX_NICKNAME_RETRY = 5
		private const val NICKNAME_UNIQUE_CONSTRAINT = "uk_user_table_nickname"
	}
}

class WithdrawnOAuthAccountException : DomainException(ErrorCode.WITHDRAWN_OAUTH_ACCOUNT)

// MAX_NICKNAME_RETRY번을 다 시도해도 닉네임 유니크 제약을 피하지 못했을 때 던진다.
// 확률상 정상적인 우연으로는 거의 발생하지 않으므로, 여기까지 오면 버그나 이상 상황일
// 가능성이 높다 — 조용히 500으로 새게 두지 않고 OAuthLoginService에서 잡아서
// 프론트로 리다이렉트시키기 위한 전용 예외.
class NicknameAssignmentFailedException(
	cause: Throwable,
) : RuntimeException("닉네임 자동 생성에 반복적으로 실패했습니다.", cause)
