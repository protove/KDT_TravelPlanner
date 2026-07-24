package com.ktcloud.travelplanner.membership.repository
import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelRole
import jakarta.persistence.LockModeType
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Lock
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.Optional
import java.util.UUID
interface TravelMemberRepository : JpaRepository<TravelMember, UUID> {
        @Lock(LockModeType.PESSIMISTIC_WRITE)
        @Query(
                """
                SELECT member
                FROM TravelMember member
                JOIN member.travel travel
                JOIN FETCH member.user user
                WHERE travel.id = :travelId
                        AND user.id = :userId
                        AND travel.deletedAt IS NULL
                """,
        )
        fun findByTravelAndUserForUpdate(
                @Param("travelId") travelId: UUID,
                @Param("userId") userId: UUID,
        ): Optional<TravelMember>
        @Query(
                """
                SELECT member
                FROM TravelMember member
                JOIN FETCH member.user user
                WHERE member.travel.id = :travelId
                        AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                ORDER BY user.id ASC
                """,
        )
        fun findAcceptedMembers(@Param("travelId") travelId: UUID): List<TravelMember>
        @Lock(LockModeType.PESSIMISTIC_WRITE)
        @Query(
                """
                SELECT member
                FROM TravelMember member
                JOIN FETCH member.user invitee
                JOIN member.travel travel
                WHERE member.id = :invitationId
                        AND travel.deletedAt IS NULL
                """,
        )
        fun findByIdForUpdate(@Param("invitationId") invitationId: UUID): Optional<TravelMember>
        @Query(
                value = """
                        SELECT member
                        FROM TravelMember member
                        JOIN FETCH member.travel travel
                        JOIN FETCH travel.owner inviter
                        JOIN FETCH member.user invitee
                        WHERE invitee.id = :userId
                                AND member.status = :status
                                AND travel.deletedAt IS NULL
                        ORDER BY member.invitedAt DESC, member.id DESC
                """,
                countQuery = """
                        SELECT COUNT(member)
                        FROM TravelMember member
                        JOIN member.travel travel
                        WHERE member.user.id = :userId
                                AND member.status = :status
                                AND travel.deletedAt IS NULL
                """,
        )
        fun findReceivedInvitations(
                @Param("userId") userId: UUID,
                @Param("status") status: InvitationStatus,
                pageable: Pageable,
        ): Page<TravelMember>
        @Query(
                """
                SELECT CASE WHEN COUNT(member) > 0 THEN TRUE ELSE FALSE END
                FROM TravelMember member
                WHERE member.travel.id = :travelId AND member.user.id = :userId
                """,
        )
        fun existsByTravelAndUser(
                @Param("travelId") travelId: UUID,
                @Param("userId") userId: UUID,
        ): Boolean
        @Query(
                """
                SELECT CASE WHEN COUNT(member) > 0 THEN TRUE ELSE FALSE END
                FROM TravelMember member
                WHERE member.travel.id = :travelId
                        AND member.user.id = :userId
                        AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                        AND member.role = com.ktcloud.travelplanner.membership.model.TravelRole.READ_WRITE
                """,
        )
        fun existsAcceptedReadWriteMember(
                @Param("travelId") travelId: UUID,
                @Param("userId") userId: UUID,
        ): Boolean
        @Query(
                """
                SELECT member.role
                FROM TravelMember member
                WHERE member.travel.id = :travelId
                        AND member.user.id = :userId
                        AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                """,
        )
        fun findAcceptedRole(
                @Param("travelId") travelId: UUID,
                @Param("userId") userId: UUID,
        ): TravelRole?

        // 이슈 #150 — 오너 탈퇴 시 소유권을 이전할 후보를 우선순위대로 조회
        // 우선순위: READ_WRITE 먼저(문자열 정렬상 DESC가 W가 O보다 뒤라 READ_WRITE가 먼저 옴)
        //          → 먼저 응답한 사람 → 동점이면 id로 결정론적 정렬
        @Query(
                """
                SELECT member
                FROM TravelMember member
                JOIN FETCH member.user user
                WHERE member.travel.id = :travelId
                        AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                ORDER BY member.role DESC, member.respondedAt ASC, member.id ASC
                """,
        )
        fun findOwnershipTransferCandidates(@Param("travelId") travelId: UUID): List<TravelMember>
}
