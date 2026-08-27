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

	@Transactional(readOnly = true)
	fun getTravels(
		userId: UUID,
		keyword: String?,
		page: Int,
		size: Int,
	): PageResponse<TravelSummaryResponse> {
		val normalizedKeyword = keyword?.trim().orEmpty()
		val result = travelRepository.findAccessibleTravels(
			userId = userId,
			keyword = normalizedKeyword,
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
