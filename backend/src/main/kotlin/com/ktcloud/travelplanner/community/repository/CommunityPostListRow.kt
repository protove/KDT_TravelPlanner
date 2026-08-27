package com.ktcloud.travelplanner.community.repository

import java.time.Instant
import java.util.UUID

// deletedAt은 기본 null — 기존 "SELECT NEW" JPQL 쿼리들(@SQLRestriction으로 이미 삭제된 행이
// 걸러진 뒤라 값이 항상 null)은 그대로 두고, 마이페이지 "내가 쓴 글" 네이티브 쿼리(MyPostRow)만
// 실제 deletedAt을 채워 넣는다. @JvmOverloads로 기존 9-인자 JPQL 생성자 매칭을 그대로 유지한다.
data class CommunityPostListRow @JvmOverloads constructor(
	val postId: UUID,
	val categoryCode: String,
	val title: String,
	val bodyPreview: String?,
	val authorNickname: String?,
	val authorProfileImageUrl: String?,
	val viewCount: Int,
	val sourceTravelId: UUID?,
	val createdAt: Instant,
	val deletedAt: Instant? = null,
)

data class CommunityPostTagNameRow(
	val postId: UUID,
	val tagName: String,
)

// findPostsOrderByPopularity 네이티브 쿼리 프로젝션 — 좋아요/댓글 수를 ORDER BY의 상관 서브쿼리로
// 계산하려면 community_reaction에 매핑된 JPA 엔티티가 없어(항상 네이티브로만 다뤄옴) JPQL로는
// 정렬식을 못 써서 쿼리 자체를 네이티브로 뺐다. deletedAt은 WHERE에서 이미 걸러서 필드가 없다.
interface PostSummaryRow {
	val postId: UUID
	val categoryCode: String
	val title: String
	val bodyPreview: String?
	val authorNickname: String?
	val authorProfileImageUrl: String?
	val viewCount: Int
	val sourceTravelId: UUID?
	val createdAt: Instant
}

// 마이페이지 "내가 쓴 글" 네이티브 쿼리 프로젝션 — @SQLRestriction을 우회해 본인이 소프트 삭제한
// 글도 함께 가져오기 위한 인터페이스. 프로퍼티 이름이 쿼리의 컬럼 별칭과 대소문자 무시로 매칭된다.
interface MyPostRow {
	val postId: UUID
	val categoryCode: String
	val title: String
	val bodyPreview: String?
	val authorNickname: String?
	val authorProfileImageUrl: String?
	val viewCount: Int
	val sourceTravelId: UUID?
	val createdAt: Instant
	val deletedAt: Instant?
}
