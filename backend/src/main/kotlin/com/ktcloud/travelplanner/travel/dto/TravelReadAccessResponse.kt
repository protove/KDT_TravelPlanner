package com.ktcloud.travelplanner.travel.dto

import java.util.UUID

// MSA 전환용 내부 API 응답. 다른 서비스(현재는 community의 "일정 기반 글쓰기" 진입)가
// 특정 travel에 대한 요청자의 조회 권한을 확인하는 데 쓴다.
// community/port/TravelAccessPort의 exists/hasReadAccess 두 메서드를 한 번의 호출로
// 채울 수 있도록 두 값을 함께 반환한다(존재하지 않음 404 vs 권한 없음 403 구분 유지).
data class TravelReadAccessResponse(
	val travelId: UUID,
	val exists: Boolean,
	val hasReadAccess: Boolean,
)
