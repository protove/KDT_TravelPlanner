package com.ktcloud.travelplanner.membership.dto

import com.ktcloud.travelplanner.membership.model.TravelRole
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size

data class TravelInvitationCreateRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	@field:Size(max = 30, message = "30자 이하여야 합니다.")
	val nickname: String,
	val role: TravelRole,
)
