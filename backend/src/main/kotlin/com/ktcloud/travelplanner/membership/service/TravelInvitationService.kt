package com.ktcloud.travelplanner.membership.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.membership.dto.ReceivedTravelInvitationResponse
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateRequest
import com.ktcloud.travelplanner.membership.dto.TravelInvitationCreateResponse
import com.ktcloud.travelplanner.membership.dto.TravelInvitationRespondRequest
import com.ktcloud.travelplanner.membership.dto.TravelInvitationStatusResponse
import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
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
class TravelInvitationService(
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val userRepository: UserRepository,
	@Qualifier("utcClock") private val clock: Clock,
) {
	@Transactional
	fun cancelInvitation(
		travelId: UUID,
		invitationId: UUID,
		requesterId: UUID,
	) {
		val invitation = travelMemberRepository.findByIdForUpdate(invitationId)
			.orElseThrow(::TravelInvitationNotFoundException)
		if (invitation.travel.id != travelId) {
			throw TravelInvitationNotFoundException()
		}
		if (invitation.travel.owner.id != requesterId) {
			throw InvitationAccessDeniedException()
		}
		if (invitation.status != InvitationStatus.PENDING) {
			throw InvitationAlreadyRespondedException()
		}
		travelMemberRepository.delete(invitation)
	}

	@Transactional
	fun respondToInvitation(
		invitationId: UUID,
		userId: UUID,
		request: TravelInvitationRespondRequest,
	): TravelInvitationStatusResponse {
		val invitation = travelMemberRepository.findByIdForUpdate(invitationId)
			.orElseThrow(::TravelInvitationNotFoundException)
		if (invitation.user.id != userId) {
			throw InvitationAccessDeniedException()
		}
		if (invitation.status != InvitationStatus.PENDING) {
			throw InvitationAlreadyRespondedException()
		}
		invitation.respond(request.action, Instant.now(clock))
		return TravelInvitationStatusResponse.from(travelMemberRepository.save(invitation))
	}

	@Transactional(readOnly = true)
	fun getReceivedInvitations(
		userId: UUID,
		status: InvitationStatus,
		page: Int,
		size: Int,
	): PageResponse<ReceivedTravelInvitationResponse> =
		PageResponse.from(
			travelMemberRepository.findReceivedInvitations(
				userId = userId,
				status = status,
				pageable = PageRequest.of(page, size),
			).map(ReceivedTravelInvitationResponse::from),
		)

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

class TravelInvitationNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class InvitationAlreadyRespondedException : DomainException(ErrorCode.CONFLICT, "이미 처리된 초대입니다.")
