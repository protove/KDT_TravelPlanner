package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.travel.dto.TravelCreateRequest
import com.ktcloud.travelplanner.travel.dto.TravelCreateResponse
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
	// 떨어뜨린다 — CommunityPostService.getPosts와 동일한 관용.
	@Transactional(readOnly = true)
	fun getTravels(
		userId: UUID,
		keyword: String?,
		searchScope: String?,
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
			pageable = PageRequest.of(page, size),
		)
		return PageResponse.from(result.map(TravelSummaryResponse::from))
	}

	companion object {
		private const val DEFAULT_SEARCH_SCOPE = "ALL"
		private val VALID_SEARCH_SCOPES = setOf("ALL", "TITLE", "DESCRIPTION", "DESTINATION")
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
