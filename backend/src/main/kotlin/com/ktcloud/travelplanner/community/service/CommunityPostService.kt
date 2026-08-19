package com.ktcloud.travelplanner.community.service

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateRequest
import com.ktcloud.travelplanner.community.dto.CommunityPostCreateResponse
import com.ktcloud.travelplanner.community.dto.CommunityPostDetailResponse
import com.ktcloud.travelplanner.community.model.CommunityPost
import com.ktcloud.travelplanner.community.model.CommunityTag
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import com.ktcloud.travelplanner.community.repository.CommunityPostRepository
import com.ktcloud.travelplanner.community.repository.CommunityTagRepository
import com.ktcloud.travelplanner.community.validation.TiptapBodyJsonValidator
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.repository.UserRepository
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
		if (request.categoryCode != SUPPORTED_CATEGORY_CODE) {
			throw UnsupportedCommunityCategoryException()
		}
		val category = communityCategoryRepository.findByCodeAndIsActiveTrue(SUPPORTED_CATEGORY_CODE)
			?: throw CommunityCategoryNotFoundException()

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
		)
		post.assignTags(tags)

		return CommunityPostCreateResponse.from(communityPostRepository.save(post))
	}

	// community-api-contract.md 2절 — 존재하지 않거나 soft delete된 게시글은 404.
	// CommunityPost의 @SQLRestriction("deleted_at IS NULL")로 findById가 이미 soft delete를 걸러준다.
	@Transactional
	fun getPostDetail(
		postId: UUID,
		requesterId: UUID?,
	): CommunityPostDetailResponse {
		val post = communityPostRepository.findById(postId).orElseThrow(::CommunityPostNotFoundException)

		communityPostRepository.incrementViewCount(postId)
		val commentCount = communityPostRepository.countActiveComments(postId)
		val reactionCount = communityPostRepository.countReactions(postId)

		return CommunityPostDetailResponse.from(
			post = post,
			bodyJson = objectMapper.readTree(post.bodyJson),
			viewCount = post.viewCount + 1,
			commentCount = commentCount,
			reactionCount = reactionCount,
			isMine = requesterId != null && requesterId == post.author.id,
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
		private const val SUPPORTED_CATEGORY_CODE = "TRAVEL_REVIEW"
		private const val MAX_TAG_COUNT = 5
		private const val TAG_NAME_MIN_LENGTH = 1
		private const val TAG_NAME_MAX_LENGTH = 20
		private const val BODY_PREVIEW_MAX_LENGTH = 120
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
