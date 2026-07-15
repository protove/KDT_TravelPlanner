package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateRequest
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateResponse
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.beans.factory.annotation.Qualifier
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Clock
import java.time.Instant
import java.util.UUID

@Service
class TravelInvitationService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val userRepository: UserRepository,
	@Qualifier("utcClock") private val clock: Clock,
) {
	@Transactional
	fun createInvitation(
		travelId: UUID,
		inviterId: UUID,
		request: TravelInvitationCreateRequest,
	): TravelInvitationCreateResponse {
		val travel = travelRepository.findById(travelId).orElseThrow(::InvitationTravelNotFoundException)
		if (travel.owner.id != inviterId) {
			throw InvitationAccessDeniedException()
		}

		val invitee = userRepository.findByNickname(request.nickname)
			?: throw InvitationTargetNotFoundException()
		val inviteeId = requireNotNull(invitee.id)
		if (inviteeId == inviterId) {
			throw SelfInvitationException()
		}
		if (travelMemberRepository.existsByTravelAndUser(travelId, inviteeId)) {
			throw DuplicateInvitationException()
		}

		val member = TravelMember(
			travel = travel,
			user = invitee,
			role = request.role,
			invitedAt = Instant.now(clock),
		)
		return TravelInvitationCreateResponse.from(travelMemberRepository.save(member))
	}
}

class InvitationTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class InvitationAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvitationTargetNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND, "초대할 사용자를 찾을 수 없습니다.")

class SelfInvitationException : DomainException(ErrorCode.INVALID_REQUEST, "자기 자신을 초대할 수 없습니다.")

class DuplicateInvitationException : DomainException(ErrorCode.CONFLICT, "이미 초대되었거나 참여 중인 사용자입니다.")
