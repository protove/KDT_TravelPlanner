package com.ktcloud.travelplanner.travel.repository
import com.ktcloud.travelplanner.travel.model.Travel
import org.springframework.data.domain.Page
import org.springframework.data.domain.Pageable
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.util.UUID
interface TravelRepository : JpaRepository<Travel, UUID> {
        // searchScope(ALL/TITLE/DESCRIPTION/DESTINATION)로 keyword 매칭 대상을 고른다 — community의
        // CommunityPostRepository와 동일한 패턴. DESTINATION은 국가명/도시명(한글·영문)을 함께 훑는다.
        // keyword가 빈 문자열이면(검색어 없음) 아래 LIKE 조건들이 전부 '%%'로 항상 참이 되어 필터링되지 않는다.
        // periodStart/periodEnd는 "여행 자체의 기간"과 겹치는지로 거른다(구간 겹침 판정) — 게시글/댓글의
        // 작성일 필터와 달리, 여행일정 검색에서 "기간"은 DB row가 언제 만들어졌는지가 아니라 실제
        // 여행 날짜가 그 기간과 겹치는지가 자연스럽다. null이면(전체 기간) 필터링하지 않는다.
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
                                AND travel.endDate >= CAST(:periodStart AS date)
                                AND travel.startDate <= CAST(:periodEnd AS date)
                                AND (
                                        (:searchScope = 'TITLE' AND LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%')))
                                        OR (:searchScope = 'DESCRIPTION' AND LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%')))
                                        OR (:searchScope = 'DESTINATION' AND (
                                                LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        ))
                                        OR (:searchScope = 'ALL' AND (
                                                LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        ))
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
                                AND travel.endDate >= CAST(:periodStart AS date)
                                AND travel.startDate <= CAST(:periodEnd AS date)
                                AND (
                                        (:searchScope = 'TITLE' AND LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%')))
                                        OR (:searchScope = 'DESCRIPTION' AND LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%')))
                                        OR (:searchScope = 'DESTINATION' AND (
                                                LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        ))
                                        OR (:searchScope = 'ALL' AND (
                                                LOWER(travel.title) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(travel.comment) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(country.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameKo) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                                OR LOWER(city.nameEn) LIKE LOWER(CONCAT('%', :keyword, '%'))
                                        ))
                                )
                """,
        )
        fun findAccessibleTravels(
                @Param("userId") userId: UUID,
                @Param("keyword") keyword: String,
                @Param("searchScope") searchScope: String,
                // "기간 없음"을 null 바인딩으로 표현하지 않는다 — CAST(:param AS date) IS NULL OR ...
                // 형태로 null을 직접 캐스트하면 Hibernate가 바인딩 타입을 못 정해(bytea로 잘못 추론)
                // "cannot cast type bytea to date"가 난다. 대신 서비스에서 필터 없음일 때 항상
                // 아주 넓은 고정 범위(0001-01-01 ~ 9999-12-31)를 채워 보내 늘 non-null 문자열만
                // 바인딩되게 한다 — keyword가 String으로 항상 안전하게 바인딩되는 것과 같은 이유.
                @Param("periodStart") periodStart: String,
                @Param("periodEnd") periodEnd: String,
                pageable: Pageable,
        ): Page<TravelListRow>

        // 이슈 #150 — 회원 탈퇴 시, 이 유저가 오너인 활성 플랜을 전부 찾기 위함
        // @SQLRestriction("deleted_at IS NULL")이 Travel 엔티티에 걸려있어서 Soft Delete된 것은 자동 제외됨
        fun findAllByOwnerId(ownerId: UUID): List<Travel>
}
