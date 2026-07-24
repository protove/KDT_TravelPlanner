package com.ktcloud.travelplanner.membership.service
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.dto.TravelMemberResponse
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID
@Service
class TravelMemberQueryService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val userRepository: UserRepository,
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
                // travel.owner.id는 FK 값이라 안전 (프록시 초기화 없이 접근 가능).
                // owner.nickname처럼 다른 필드는 직접 못 읽으므로(탈퇴 시 예외 위험, 이슈 #150),
                // 우회 조회(findOwnerDisplayById)로 안전하게 가져온다.
                val ownerId = requireNotNull(travel.owner.id)
                val ownerProjection = userRepository.findOwnerDisplayById(ownerId)
                val ownerIsDeleted = ownerProjection?.getDeletedAt() != null
                val owner = TravelMemberResponse.fromOwner(
                        ownerId = ownerId,
                        nickname = if (ownerIsDeleted) "탈퇴한 사용자" else ownerProjection?.getNickname(),
                        profileImageUrl = if (ownerIsDeleted) null else ownerProjection?.getProfileImageUrl(),
                )
                val members = travelMemberRepository.findAcceptedMembers(travelId).map(TravelMemberResponse::fromMember)
                return listOf(owner) + members
        }
}
class MemberTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)
class TravelMemberAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)
