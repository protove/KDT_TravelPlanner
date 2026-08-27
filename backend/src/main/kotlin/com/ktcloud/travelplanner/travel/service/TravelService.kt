package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.dto.TravelCreateRequest
import com.ktcloud.travelplanner.travel.dto.TravelCreateResponse
import com.ktcloud.travelplanner.travel.dto.TravelReadAccessResponse
import com.ktcloud.travelplanner.travel.dto.TravelSummaryResponse
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.data.domain.PageRequest
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.util.UUID

@Service
class TravelService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val userRepository: UserRepository,
	@Qualifier("utcClock") private val clock: Clock,
) {
	@Transactional
	fun createTravel(
		ownerId: UUID,
		request: TravelCreateRequest,
	): TravelCreateResponse {
		val owner = userRepository.findById(ownerId).orElseThrow(::TravelOwnerNotFoundException)
		val travel = Travel(
			owner = owner,
			title = request.title,
			startDate = request.startDate,
			endDate = request.endDate,
		)
		return TravelCreateResponse.from(travelRepository.save(travel))
	}

	// searchScope는 화이트리스트 밖 값(오타/구버전 클라이언트 등)이면 조용히 기본값(ALL)으로
	// 떨어뜨린다 — CommunityPostService.getPosts와 동일한 관용. periodStart/periodEnd는 둘 다
	// null이면(기간 필터 없음) 전체 기간을 그대로 조회한다 — 화면 쪽에서 기본값으로 좁혀서 보내는
	// 것을 기대하지만, 백엔드 계약 자체는 "필터 없음"을 명시적으로 허용한다.
	@Transactional(readOnly = true)
	fun getTravels(
		userId: UUID,
		keyword: String?,
		searchScope: String?,
		periodStart: LocalDate?,
		periodEnd: LocalDate?,
		page: Int,
		size: Int,
	): PageResponse<TravelSummaryResponse> {
		val normalizedKeyword = keyword?.trim().orEmpty()
		val normalizedSearchScope = searchScope?.trim()?.uppercase()?.takeIf { it in VALID_SEARCH_SCOPES }
			?: DEFAULT_SEARCH_SCOPE
		val result = travelRepository.findAccessibleTravels(
			userId = userId,
			keyword = normalizedKeyword,
			searchScope = normalizedSearchScope,
			periodStart = (periodStart ?: MIN_PERIOD_DATE).toString(),
			periodEnd = (periodEnd ?: MAX_PERIOD_DATE).toString(),
			pageable = PageRequest.of(page, size),
		)
		return PageResponse.from(result.map(TravelSummaryResponse::from))
	}

	// MSA 전환용 내부 API — CommunityPostService.verifySourceTravelReadAccess가 하던
	// "travelRepository.findById + travelMemberRepository.findAcceptedRole" 조합을 Travel 서비스
	// 소유 로직으로 옮긴 것. 존재하지 않으면 예외 대신 exists=false로 응답한다(호출 측이
	// 404/403을 구분해서 처리할 수 있도록). 소프트 삭제된 travel은 @SQLRestriction으로
	// findById에서 걸러지므로 exists=false가 된다.
	@Transactional(readOnly = true)
	fun checkReadAccess(
		travelId: UUID,
		requesterId: UUID,
	): TravelReadAccessResponse {
		val travel = travelRepository.findById(travelId).orElse(null)
			?: return TravelReadAccessResponse(travelId, exists = false, hasReadAccess = false)
		val hasReadAccess = travel.owner.id == requesterId ||
			travelMemberRepository.findAcceptedRole(travelId, requesterId) != null
		return TravelReadAccessResponse(travelId, exists = true, hasReadAccess = hasReadAccess)
	}

	companion object {
		private const val DEFAULT_SEARCH_SCOPE = "ALL"
		private val VALID_SEARCH_SCOPES = setOf("ALL", "TITLE", "DESCRIPTION", "DESTINATION")

		// periodStart/periodEnd가 null(기간 필터 없음)일 때 항상 non-null 문자열만 바인딩되도록
		// 채우는 사실상 무제한 경계값. LocalDate.MIN/MAX 대신 postgres date 타입 안전 범위 안의
		// 값을 쓴다.
		private val MIN_PERIOD_DATE: LocalDate = LocalDate.of(1, 1, 1)
		private val MAX_PERIOD_DATE: LocalDate = LocalDate.of(9999, 12, 31)
	}

	@Transactional
	fun deleteTravel(
		travelId: UUID,
		requesterId: UUID,
	) {
		val travel = travelRepository.findById(travelId).orElseThrow(::TravelNotFoundException)
		if (travel.isDeleted) {
			throw TravelNotFoundException()
		}
		if (travel.owner.id != requesterId) {
			throw TravelDeleteAccessDeniedException()
		}
		travel.softDelete(Instant.now(clock))
		travelRepository.saveAndFlush(travel)
	}
}

class TravelOwnerNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelDeleteAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)
