package com.ktcloud.travelplanner.community.adapter

import com.ktcloud.travelplanner.community.port.TravelAccessPort
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Component
import java.util.UUID

// 임시 구현체 — 지금은 같은 프로세스 안이라 TravelRepository/TravelMemberRepository를
// 그대로 감싸서 쓴다. travel 도메인이 실제로 분리되거나, community가 별도 서비스로
// 배포되는 시점에 이 클래스를 `GET /api/v1/travels/{travelId}/read-access` 호출
// 기반 어댑터로 교체한다.
@Component
class JpaTravelAccessAdapter(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
) : TravelAccessPort {
	override fun exists(travelId: UUID): Boolean = travelRepository.existsById(travelId)

	override fun hasReadAccess(
		travelId: UUID,
		requesterId: UUID,
	): Boolean {
		val travel = travelRepository.findById(travelId).orElse(null) ?: return false
		return travel.owner.id == requesterId ||
			travelMemberRepository.findAcceptedRole(travelId, requesterId) != null
	}
}
