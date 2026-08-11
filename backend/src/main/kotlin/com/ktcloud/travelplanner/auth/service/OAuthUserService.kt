package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class OAuthUserService(
	private val userRepository: UserRepository,
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

		return userRepository.save(
			User(
				provider = profile.provider,
				providerUserId = profile.providerUserId,
				email = profile.email,
				name = profile.name,
			).also {
				it.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			},
		)
	}
}

class WithdrawnOAuthAccountException : DomainException(ErrorCode.WITHDRAWN_OAUTH_ACCOUNT)
