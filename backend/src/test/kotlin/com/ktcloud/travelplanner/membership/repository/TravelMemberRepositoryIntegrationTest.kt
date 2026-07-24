package com.ktcloud.travelplanner.membership.repository

import com.ktcloud.travelplanner.membership.model.TravelInvitationAction
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.testsupport.TestcontainersConfiguration
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import com.ktcloud.travelplanner.user.repository.UserRepository
import jakarta.persistence.EntityManager
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.context.annotation.Import
import org.springframework.test.context.ActiveProfiles
import org.springframework.transaction.annotation.Transactional
import java.time.Instant
import java.time.LocalDate
import java.util.UUID
import kotlin.test.assertEquals

@ActiveProfiles("test")
@SpringBootTest
@Import(TestcontainersConfiguration::class)
@Transactional
class TravelMemberRepositoryIntegrationTest(
        @Autowired private val userRepository: UserRepository,
        @Autowired private val travelRepository: TravelRepository,
        @Autowired private val travelMemberRepository: TravelMemberRepository,
        @Autowired private val entityManager: EntityManager,
) {
        // 이슈 #150 — responded_at이 완전히 같은 멤버가 여러 명일 때,
        // 최종 tie-breaker(id ASC)로 항상 같은 순서가 나오는지 검증
        @Test
        fun `ownership transfer candidates use id as tie-breaker when responded_at is identical`() {
                val owner = saveUser("tie-owner")
                val travel = saveTravel(owner)

                val sameRespondedAt = Instant.parse("2026-07-01T00:00:00Z")
                val laterId = UUID.fromString("00000000-0000-0000-0000-000000000002")
                val earlierId = UUID.fromString("00000000-0000-0000-0000-000000000001")

                // 일부러 큰 id부터 먼저 저장 — "저장 순서"가 아니라 "id 값 자체"로 정렬되는지 확인하기 위함
                saveAcceptedMember(laterId, travel, saveUser("member-later"), TravelRole.READ_WRITE, sameRespondedAt)
                saveAcceptedMember(earlierId, travel, saveUser("member-earlier"), TravelRole.READ_WRITE, sameRespondedAt)
                entityManager.clear()

                val candidates = travelMemberRepository.findOwnershipTransferCandidates(travel.id)

                assertEquals(earlierId, candidates.first().id)
        }

        // 참고 — 기존 정책(우선순위: READ_WRITE 먼저, 그다음 먼저 응답한 사람)도 같이 확인
        @Test
        fun `ownership transfer candidates prioritize read write role over responded time`() {
                val owner = saveUser("priority-owner")
                val travel = saveTravel(owner)

                val readOnlyFirst = saveAcceptedMember(
                        UUID.fromString("00000000-0000-0000-0000-000000000010"),
                        travel,
                        saveUser("read-only-first"),
                        TravelRole.READ_ONLY,
                        Instant.parse("2026-07-01T00:00:00Z"),
                )
                val readWriteLater = saveAcceptedMember(
                        UUID.fromString("00000000-0000-0000-0000-000000000011"),
                        travel,
                        saveUser("read-write-later"),
                        TravelRole.READ_WRITE,
                        Instant.parse("2026-07-02T00:00:00Z"),
                )
                entityManager.clear()

                val candidates = travelMemberRepository.findOwnershipTransferCandidates(travel.id)

                assertEquals(readWriteLater.id, candidates.first().id)
                assertEquals(readOnlyFirst.id, candidates.last().id)
        }

        private fun saveAcceptedMember(
                id: UUID,
                travel: Travel,
                user: User,
                role: TravelRole,
                respondedAt: Instant,
        ): TravelMember {
                val member = TravelMember(
                        id = id,
                        travel = travel,
                        user = user,
                        role = role,
                        invitedAt = respondedAt,
                ).also { it.respond(TravelInvitationAction.ACCEPT, respondedAt) }
                return travelMemberRepository.saveAndFlush(member)
        }

        private fun saveUser(nickname: String): User = userRepository.saveAndFlush(
                User(
                        provider = OAuthProvider.GOOGLE,
                        providerUserId = "tie-${UUID.randomUUID()}",
                ).also { it.completeProfile(nickname, null, null) },
        )

        private fun saveTravel(owner: User): Travel = travelRepository.saveAndFlush(
                Travel(
                        owner = owner,
                        title = "동점 테스트 여행",
                        startDate = LocalDate.parse("2026-08-01"),
                        endDate = LocalDate.parse("2026-08-03"),
                ),
        )
}
