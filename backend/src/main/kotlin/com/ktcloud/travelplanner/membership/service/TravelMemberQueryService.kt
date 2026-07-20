package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.dto.TravelMemberResponse
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TravelMemberQueryService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
) {
	@Transactional(readOnly = true)
	fun getTravelMembers(
		travelId: UUID,
		requesterId: UUID,
	): List<TravelMemberResponse> {
		val travel = travelRepository.findById(travelId).orElseThrow(::MemberTravelNotFoundException)
		if (travel.owner.id != requesterId && travelMemberRepository.findAcceptedRole(travelId, requesterId) == null) {
			throw TravelMemberAccessDeniedException()
		}

		val owner = TravelMemberResponse.fromOwner(travel.owner)
		val members = travelMemberRepository.findAcceptedMembers(travelId).map(TravelMemberResponse::fromMember)
		return listOf(owner) + members
	}
}

class MemberTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelMemberAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)
