package com.ktcloud.travelplanner.auth.service

import com.ktcloud.travelplanner.auth.client.OAuthUserProfile
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import com.ktcloud.travelplanner.user.service.NicknameGenerator
import org.springframework.stereotype.Component
import org.springframework.transaction.annotation.Propagation
import org.springframework.transaction.annotation.Transactional

// 신규 SSO 유저 저장을 독립된 트랜잭션(REQUIRES_NEW)으로 분리한 컴포넌트.
//
// Postgres는 트랜잭션 안에서 유니크 제약 위반이 한 번 발생하면 해당 트랜잭션 전체가
// abort 상태가 되어, 같은 트랜잭션 안에서는 이후 어떤 쿼리도 실패한다.
// 닉네임 충돌로 저장이 실패했을 때 "새 닉네임으로 재시도"가 실제로 동작하려면
// 시도마다 완전히 독립된 트랜잭션이어야 하므로, 저장 로직을 별도 컴포넌트/트랜잭션으로 뺐다.
@Component
class OAuthNewUserRegistrar(
	private val userRepository: UserRepository,
	private val nicknameGenerator: NicknameGenerator,
) {
	@Transactional(propagation = Propagation.REQUIRES_NEW)
	fun register(profile: OAuthUserProfile): User {
		val user = User(
			provider = profile.provider,
			providerUserId = profile.providerUserId,
			email = profile.email,
			name = profile.name,
		).also {
			it.updateOAuthProfile(profile.email, profile.name, profile.profileImageUrl)
			it.assignGeneratedNickname(nicknameGenerator.generate())
		}
		return userRepository.saveAndFlush(user)
	}
}
