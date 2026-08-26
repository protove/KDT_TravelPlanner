package com.ktcloud.travelplanner.travel.repository
import com.ktcloud.travelplanner.travel.model.Travel
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID
interface TravelRepository : JpaRepository<Travel, UUID> {
        @Query(
                value = """
                        SELECT new com.ktcloud.travelplanner.travel.repository.TravelListRow(
                                travel.id,
                                travel.title,
                                travel.startDate,
                                travel.endDate,
                                country.id,
                                city.id,
                                travel.participantCount,
                                travel.updatedAt,
                                member.role
                        )
                        FROM Travel travel
                        LEFT JOIN travel.country country
                        LEFT JOIN travel.city city
                        LEFT JOIN TravelMember member
                                ON member.travel = travel
                                AND member.user.id = :userId
                                AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                        WHERE (travel.owner.id = :userId OR member.id IS NOT NULL)
                                AND (
                                        LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                )
                        ORDER BY travel.updatedAt DESC, travel.id DESC
                """,
                countQuery = """
                        SELECT COUNT(travel)
                        FROM Travel travel
                        LEFT JOIN travel.country country
                        LEFT JOIN travel.city city
                        LEFT JOIN TravelMember member
                                ON member.travel = travel
                                AND member.user.id = :userId
                                AND member.status = com.ktcloud.travelplanner.membership.model.InvitationStatus.ACCEPTED
                        WHERE (travel.owner.id = :userId OR member.id IS NOT NULL)
                                AND (
                                        LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                )
                """,
        )
        fun findAccessibleTravels(
                @Param("userId") userId: UUID,
                @Param("keyword") keyword: String,
                pageable: Pageable,
        ): Page<TravelListRow>

        // 이슈 #150 — 회원 탈퇴 시, 이 유저가 오너인 활성 플랜을 전부 찾기 위함
        // @SQLRestriction("deleted_at IS NULL")이 Travel 엔티티에 걸려있어서 Soft Delete된 것은 자동 제외됨
        fun findAllByOwnerId(ownerId: UUID): List<Travel>
}
