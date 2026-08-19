package com.ktcloud.travelplanner.community.dto

import com.fasterxml.jackson.databind.JsonNode
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.NotNull
import jakarta.validation.constraints.Size
import java.util.UUID

// community-api-contract.md 1절 CommunityPostCreateRequest.
// bodyPreview는 인터페이스에 없으므로 요청으로 받지 않고 서버가 bodyJson으로부터 생성한다(6-3절).
data class CommunityPostCreateRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	val categoryCode: String,
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	@field:Size(max = 200, message = "200자 이하여야 합니다.")
	val title: String,
	@field:NotNull(message = "본문이 필요합니다.")
	val bodyJson: JsonNode,
	val tags: List<String>? = null,
	val sourceTravelId: UUID? = null,
)
