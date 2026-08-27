package com.ktcloud.travelplanner.community.port

import java.util.UUID

// community가 travel/membership 도메인을 직접(Repository/Entity) 참조하지 않고 이 인터페이스로만
// 접근하게 끊어두는 경계. CommunityPostService.verifySourceTravelReadAccess가 하던
// "travelRepository.findById + travelMemberRepository.findAcceptedRole" 조합을 대체한다.
// travel은 이번 스코프에서 분리하지 않고 모놀리스에 남지만, community가 실제로 별도 서비스로
// 배포되면 이 프로세스 경계 자체가 네트워크 경계가 되므로 지금부터 인터페이스로 끊어둔다.
// 실제 배포 분리 시점에는 JpaTravelAccessAdapter를
// `GET /api/v1/travels/{travelId}/read-access` 호출로 교체하면 된다.
interface TravelAccessPort {
	fun exists(travelId: UUID): Boolean

	fun hasReadAccess(travelId: UUID, requesterId: UUID): Boolean
}
