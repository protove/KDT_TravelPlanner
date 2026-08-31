package com.ktcloud.travelplanner.community.dto

import com.fasterxml.jackson.databind.JsonNode
import com.ktcloud.travelplanner.global.dto.PatchField
import jakarta.validation.constraints.PositiveOrZero

// community-api-contract.md 1절 CommunityPostUpdatePatch. categoryCode/sourceTravelId/
// itinerarySnapshotJson은 계약상 수정 대상이 아니다(불변). tags를 보내면 기존 연결을 전부
// 지우고 새로 넣는다(부분 추가 아님).
data class CommunityPostUpdateRequest(
	val title: PatchField<String> = PatchField.Absent,
	val bodyJson: PatchField<JsonNode> = PatchField.Absent,
	val tags: PatchField<List<String>> = PatchField.Absent,
	@field:PositiveOrZero(message = "0 이상이어야 합니다.")
	val version: Int,
)
