package com.ktcloud.travelplanner.community.service

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostDetailResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostSummaryResponse
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.community.validation.TiptapBodyJsonValidator
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.global.response.PageResponse
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.data.domain.PageRequest
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class CommunityPostService(
	private val communityCategoryRepository: CommunityCategoryRepository,
	private val communityTagRepository: CommunityTagRepository,
	private val communityPostRepository: CommunityPostRepository,
	private val userRepository: UserRepository,
	private val travelRepository: TravelRepository,
	private val travelMemberRepository: TravelMemberRepository,
	private val objectMapper: ObjectMapper,
) {
	@Transactional
	fun createPost(
		authorId: UUID,
		request: CommunityPostCreateRequest,
	): CommunityPostCreateResponse {
		if (request.categoryCode == NOTICE_CATEGORY_CODE) {
			throw UnsupportedCommunityCategoryException()
		}
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue(request.categoryCode)
			?: throw CommunityCategoryNotFoundException()

		// itinerarySnapshotJson은 bodyJson과 달리 Tiptap 문서가 아니라(일정 자체의 day/장소 구조 +
		// 좌표) 프론트가 작성 시점에 한 번 조립해서 보내는 불변 스냅샷이라 화이트리스트 검증 대상이 아니다.
		TiptapBodyJsonValidator.validate(request.bodyJson)

		val author = userRepository.findById(authorId).orElseThrow(::CommunityPostAuthorNotFoundException)

		if (request.sourceTravelId != null) {
			verifySourceTravelReadAccess(request.sourceTravelId, authorId)
		}

		val tags = normalizeTagNames(request.tags).map(::findOrCreateTag).toSet()

		val post = CommunityPost(
			author = author,
			category = category,
			title = request.title,
			bodyJson = request.bodyJson.toString(),
			bodyPreview = buildBodyPreview(request.bodyJson),
			sourceTravelId = request.sourceTravelId,
			itinerarySnapshotJson = request.itinerarySnapshotJson?.toString(),
		)
		post.assignTags(tags)

		return CommunityPostCreateResponse.from(communityPostRepository.save(post))
	}

	// community-api-contract.md 2절 — 존재하지 않거나 soft delete된 게시글은 404.
	// CommunityPost의 @SQLRestriction("deleted_at IS NULL")로 findById가 이미 soft delete를 걸러준다.
	// existsById를 별도로 부르지 않고 findById 결과를 존재 확인 + 조회에 그대로 재사용한다.
	// incrementViewCount(clearAutomatically=true)는 영속성 컨텍스트를 통째로 비워서 post를
	// detach시키므로, post.author/category/tags 같은 LAZY 연관관계 접근(응답 DTO 조립)은
	// 반드시 increment 호출 이전에 전부 끝내야 한다 (그렇지 않으면 LazyInitializationException).
	// viewCount는 increment 이후 값을 다시 조회하지 않고, 조회 시점 값에 +1을 더해 응답한다.
	@Transactional
	fun getPostDetail(
		postId: UUID,
		requesterId: UUID?,
	): CommunityPostDetailResponse {
		val post = communityPostRepository.findById(postId).orElseThrow(::CommunityPostNotFoundException)
		val commentCount = communityPostRepository.countActiveComments(postId)
		val reactionCount = communityPostRepository.countReactions(postId)

		val response = CommunityPostDetailResponse.from(
			post = post,
			bodyJson = objectMapper.readTree(post.bodyJson),
			itinerarySnapshotJson = post.itinerarySnapshotJson?.let(objectMapper::readTree),
			viewCount = post.viewCount + 1,
			commentCount = commentCount,
			reactionCount = reactionCount,
			isMine = requesterId != null && requesterId == post.author.id,
		)
		communityPostRepository.incrementViewCount(postId)
		return response
	}

	// community-api-contract.md 2절/3절 — 목록 조회. 인증 불필요.
	@Transactional(readOnly = true)
	fun getPosts(
		categoryCode: String?,
		tagName: String?,
		keyword: String?,
		sort: String?,
		page: Int,
		size: Int,
	): PageResponse<CommunityPostSummaryResponse> {
		val normalizedCategoryCode = categoryCode?.trim()?.takeIf { it.isNotEmpty() }
		val normalizedTagName = tagName?.trim()?.takeIf { it.isNotEmpty() }
		val normalizedKeyword = keyword?.trim()?.takeIf { it.isNotEmpty() }
		val pageable = PageRequest.of(page.coerceAtLeast(0), size.coerceIn(MIN_PAGE_SIZE, MAX_PAGE_SIZE))

		val result = if (sort == SORT_POPULAR) {
			communityPostRepository.findPostsOrderByPopularity(normalizedCategoryCode, normalizedTagName, normalizedKeyword, pageable)
		} else {
			communityPostRepository.findPostsOrderByCreatedAt(normalizedCategoryCode, normalizedTagName, normalizedKeyword, pageable)
		}

		val postIds = result.content.map { it.postId }
		val tagsByPostId = if (postIds.isEmpty()) {
			emptyMap()
		} else {
			communityPostRepository.findTagNamesByPostIds(postIds).groupBy({ it.postId }, { it.tagName })
		}

		return PageResponse.from(
			result.map { row -> CommunityPostSummaryResponse.from(row, tagsByPostId[row.postId].orEmpty()) },
		)
	}

	// community-api-contract.md 0절 — 일정 기반 작성 진입은 해당 travel에 대한 조회 권한 보유자
	// (OWNER/READ_ONLY/READ_WRITE, ACCEPTED)만 가능. TravelMemberQueryService.getTravelMembers와
	// 동일한 권한 체크(오너 본인이거나 ACCEPTED 멤버여야 함)를 재검증한다.
	private fun verifySourceTravelReadAccess(
		travelId: UUID,
		requesterId: UUID,
	) {
		val travel = travelRepository.findById(travelId).orElseThrow(::CommunityPostSourceTravelNotFoundException)
		if (travel.owner.id != requesterId && travelMemberRepository.findAcceptedRole(travelId, requesterId) == null) {
			throw CommunityPostSourceTravelAccessDeniedException()
		}
	}

	// community-api-contract.md 4절 — trim 후 1~20자, 게시글당 최대 5개, 대소문자 구분 정확히 일치.
	private fun normalizeTagNames(tags: List<String>?): List<String> {
		if (tags.isNullOrEmpty()) return emptyList()

		val normalized = tags.map { it.trim() }.distinct()
		if (normalized.size > MAX_TAG_COUNT) {
			throw TooManyCommunityTagsException()
		}
		normalized.forEach { name ->
			if (name.length !in TAG_NAME_MIN_LENGTH..TAG_NAME_MAX_LENGTH) {
				throw InvalidCommunityTagNameException()
			}
		}
		return normalized
	}

	private fun findOrCreateTag(name: String): CommunityTag {
		communityTagRepository.findByName(name)?.let { return it }
		communityTagRepository.insertIgnoringConflict(name)
		return communityTagRepository.findByName(name)
			?: error("community_tag insert succeeded but re-select found no row for name=$name")
	}

	// community-api-contract.md 6-3절 — 모든 text 노드를 공백으로 join → 앞 120자 → 말줄임표.
	private fun buildBodyPreview(bodyJson: JsonNode): String {
		val text = StringBuilder()
		collectText(bodyJson, text)
		val joined = text.toString()
		return if (joined.length > BODY_PREVIEW_MAX_LENGTH) {
			joined.substring(0, BODY_PREVIEW_MAX_LENGTH) + "…"
		} else {
			joined
		}
	}

	private fun collectText(
		node: JsonNode,
		out: StringBuilder,
	) {
		if (node.get("type")?.asText() == "text") {
			val value = node.get("text")?.asText().orEmpty()
			if (value.isNotEmpty()) {
				if (out.isNotEmpty()) out.append(' ')
				out.append(value)
			}
		}
		node.get("content")?.takeIf { it.isArray }?.forEach { collectText(it, out) }
	}

	companion object {
		private const val NOTICE_CATEGORY_CODE = "NOTICE"
		private const val MAX_TAG_COUNT = 5
		private const val TAG_NAME_MIN_LENGTH = 1
		private const val TAG_NAME_MAX_LENGTH = 20
		private const val BODY_PREVIEW_MAX_LENGTH = 120
		private const val SORT_POPULAR = "popular"
		private const val MIN_PAGE_SIZE = 1
		private const val MAX_PAGE_SIZE = 50
	}
}

class UnsupportedCommunityCategoryException :
	DomainException(ErrorCode.VALIDATION_ERROR, "현재 지원하지 않는 카테고리입니다.")

class CommunityCategoryNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityPostAuthorNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityPostNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityPostSourceTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class CommunityPostSourceTravelAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class TooManyCommunityTagsException :
	DomainException(ErrorCode.VALIDATION_ERROR, "태그는 최대 5개까지 등록할 수 있습니다.")

class InvalidCommunityTagNameException :
	DomainException(ErrorCode.VALIDATION_ERROR, "태그는 1~20자여야 합니다.")
