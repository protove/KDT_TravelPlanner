package com.ktcloud.travelplanner.user.service
import com.ktcloud.travelplanner.auth.service.RefreshTokenService
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
class UserAccountService(
        private val userRepository: UserRepository,
        private val refreshTokenService: RefreshTokenService,
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        @Qualifier("utcClock") private val clock: Clock,
) {
        @Transactional
        fun deleteAccount(
                userId: UUID,
                refreshToken: String?,
        ) {
                val user = userRepository.findById(userId)
                        .orElseThrow(::UserNotFoundException)

                // 이슈 #150 — 이 유저가 오너인 활성 플랜마다, 다른 멤버가 있으면 소유권 이전
                val ownedTravels = travelRepository.findAllByOwnerId(userId)
                for (travel in ownedTravels) {
                        val candidate = travelMemberRepository
                                .findOwnershipTransferCandidates(travel.id)
                                .firstOrNull()
                        if (candidate != null) {
                                travel.transferOwnership(candidate.user)
                                travelMemberRepository.delete(candidate)
                        }
                        // candidate가 없으면(멤버 없음) 아무 것도 안 함 — owner_id는 탈퇴 유저를 계속 가리킴
                }

                user.softDelete(Instant.now(clock))
                userRepository.saveAndFlush(user)
                refreshTokenService.revoke(refreshToken)
        }
}
