package com.ktcloud.travelplanner.user.repository
import com.ktcloud.travelplanner.user.model.OAuthProvider
import com.ktcloud.travelplanner.user.model.User
import org.springframework.data.jpa.repository.JpaRepository
import org.springframework.data.jpa.repository.Query
import org.springframework.data.repository.query.Param
import java.time.Instant
import java.util.UUID
interface UserRepository : JpaRepository<User, UUID> {
        fun findByProviderAndProviderUserId(
                provider: OAuthProvider,
                providerUserId: String,
        ): User?
        fun findByNickname(nickname: String): User?
        fun existsByNickname(nickname: String): Boolean

        // 이슈 #150 — User 엔티티엔 @SQLRestriction("deleted_at IS NULL")이 걸려있어서
        // 일반적인 방법으로는 탈퇴한 유저를 조회할 수 없음(0건으로 취급됨).
        // "탈퇴한 사용자"로 표시하려면 탈퇴 여부와 무관하게 조회해야 하므로 Native Query로 우회.
        @Query(
                value = """
                        SELECT nickname, profile_image_url AS profileImageUrl, deleted_at AS deletedAt
                        FROM user_table
                        WHERE id = :userId
                """,
                nativeQuery = true,
        )
        fun findOwnerDisplayById(@Param("userId") userId: UUID): OwnerDisplayProjection?
}

interface OwnerDisplayProjection {
        fun getNickname(): String?
        fun getProfileImageUrl(): String?
        fun getDeletedAt(): Instant?
}
