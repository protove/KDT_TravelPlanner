package com.ktcloud.travelplanner.community.port

import java.util.UUID

// community가 user 도메인을 직접(Repository/Entity) 참조하지 않고 이 인터페이스로만 접근하게
// 끊어두는 경계. 지금은 JpaUserLookupAdapter(같은 프로세스, UserRepository 그대로 사용)가
// 구현체지만, Identity 서비스가 실제로 분리되면 이 인터페이스는 그대로 두고 구현체만
// HTTP 클라이언트 기반으로 교체한다 — community 쪽 서비스 코드는 변경할 필요가 없다.
interface UserLookupPort {
	fun findAuthor(userId: UUID): AuthorSummary?
}

// User 엔티티 전체가 아니라 community가 실제로 필요한 필드만 담는다(email/gender/생년 등
// 민감 정보는 애초에 노출하지 않음 — user/dto/UserProfileResponse.kt는 전체 프로필이라
// 이 용도로 그대로 못 쓴다).
data class AuthorSummary(
	val id: UUID,
	val nickname: String?,
	val profileImageUrl: String?,
)
