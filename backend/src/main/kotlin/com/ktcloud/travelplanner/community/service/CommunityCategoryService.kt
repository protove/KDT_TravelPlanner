package com.ktcloud.travelplanner.community.service

import com.ktcloud.travelplanner.community.dto.CommunityCategoryResponse
import com.ktcloud.travelplanner.community.repository.CommunityCategoryRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class CommunityCategoryService(
	private val communityCategoryRepository: CommunityCategoryRepository,
) {
	// excludeNotice=true인 호출(글쓰기 화면)은 NOTICE 행 자체를 DB 조회 단계에서 걸러낸다 —
	// 공지사항은 관리자 전용 플로우로 다룰 예정(community-api-contract.md 부록 3)이라
	// 일반 글쓰기 카테고리로는 노출도, 로드도 되면 안 된다.
	@Transactional(readOnly = true)
	fun getCategories(excludeNotice: Boolean = false): List<CommunityCategoryResponse> {
		val categories = if (excludeNotice) {
			communityCategoryRepository.findAllByIsActiveTrueAndCodeNotOrderBySortOrderAscIdAsc(NOTICE_CATEGORY_CODE)
		} else {
			communityCategoryRepository.findAllByIsActiveTrueOrderBySortOrderAscIdAsc()
		}
		return categories.map(CommunityCategoryResponse::from)
	}

	companion object {
		private const val NOTICE_CATEGORY_CODE = "NOTICE"
	}
}
