package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.dto.TravelMemberResponse
import com.ktcloud.travelplanner.membership.dto.TravelMemberRoleUpdateRequest
import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TravelMemberService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
) {
	@Transactional
	fun updateMemberRole(
		travelId: UUID,
		memberId: UUID,
		requesterId: UUID,
		request: TravelMemberRoleUpdateRequest,
	): TravelMemberResponse {
		val travel = travelRepository.findById(travelId).orElseThrow(::MemberTravelNotFoundException)
		if (travel.owner.id != requesterId) {
			throw TravelMemberAccessDeniedException()
		}
		if (travel.owner.id == memberId) {
			throw TravelOwnerRoleUpdateException()
		}

		val member = travelMemberRepository.findByTravelAndUserForUpdate(travelId, memberId)
			.orElseThrow(::TravelMemberNotFoundException)
		if (member.status != InvitationStatus.ACCEPTED) {
			throw PendingTravelMemberRoleUpdateException()
		}
		member.updateRole(request.role)
		return TravelMemberResponse.fromMember(travelMemberRepository.save(member))
	}
}

class TravelMemberNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelOwnerRoleUpdateException : DomainException(ErrorCode.INVALID_REQUEST, "플랜 소유자의 권한은 변경할 수 없습니다.")

class PendingTravelMemberRoleUpdateException : DomainException(ErrorCode.INVALID_REQUEST, "수락된 참여자의 권한만 변경할 수 있습니다.")
