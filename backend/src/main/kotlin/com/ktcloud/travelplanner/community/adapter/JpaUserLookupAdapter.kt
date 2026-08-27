package com.ktcloud.travelplanner.community.adapter

import com.ktcloud.travelplanner.community.port.AuthorSummary
import com.ktcloud.travelplanner.community.port.UserLookupPort
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Component
import java.util.UUID

// 임시 구현체 — 지금은 같은 프로세스 안이라 UserRepository를 그대로 감싸서 쓴다.
// Identity 서비스가 실제로 분리되면 이 클래스만 HTTP 클라이언트 기반 어댑터로 교체한다.
@Component
class JpaUserLookupAdapter(
	private val userRepository: UserRepository,
) : UserLookupPort {
	override fun findAuthor(userId: UUID): AuthorSummary? =
		userRepository.findById(userId).map {
			AuthorSummary(id = it.id, nickname = it.nickname, profileImageUrl = it.profileImageUrl)
		}.orElse(null)
}
