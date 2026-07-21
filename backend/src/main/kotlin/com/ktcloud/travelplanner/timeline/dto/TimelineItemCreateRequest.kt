package com.ktcloud.travelplanner.timeline.dto
import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import jakarta.validation.constraints.DecimalMax
import jakarta.validation.constraints.DecimalMin
import jakarta.validation.constraints.Digits
import jakarta.validation.constraints.Max
import jakarta.validation.constraints.Min
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Positive
import jakarta.validation.constraints.Size
import java.math.BigDecimal
import java.time.LocalDate
data class TimelineItemCreateRequest(
        @field:Min(1, message = "1 이상이어야 합니다.")
        @field:Max(32767, message = "32767 이하여야 합니다.")
        val dayNumber: Int?,
        val visitDate: LocalDate?,
        @field:Positive(message = "양수여야 합니다.")
        val cityId: Long?,
        val category: TimelineCategory,
        @field:Size(max = 30, message = "30자 이하여야 합니다.")
        val foodSubcategory: String?,
        @field:NotBlank(message = "비어 있을 수 없습니다.")
        @field:Size(max = 100, message = "100자 이하여야 합니다.")
        val name: String,
        @field:Size(max = 255, message = "255자 이하여야 합니다.")
        val googlePlaceId: String?,
        @field:DecimalMin(value = "-90", message = "-90 이상이어야 합니다.")
        @field:DecimalMax(value = "90", message = "90 이하여야 합니다.")
        @field:Digits(integer = 3, fraction = 6, message = "소수점 6자리 이하여야 합니다.")
        val latitude: BigDecimal?,
        @field:DecimalMin(value = "-180", message = "-180 이상이어야 합니다.")
        @field:DecimalMax(value = "180", message = "180 이하여야 합니다.")
        @field:Digits(integer = 3, fraction = 6, message = "소수점 6자리 이하여야 합니다.")
        val longitude: BigDecimal?,
        @field:DecimalMin(value = "0", message = "0 이상이어야 합니다.")
        @field:DecimalMax(value = "5", message = "5 이하여야 합니다.")
        @field:Digits(integer = 1, fraction = 1, message = "소수점 1자리 이하여야 합니다.")
        val rating: BigDecimal?,
        @field:Min(1, message = "1 이상이어야 합니다.")
        @field:Max(32767, message = "32767 이하여야 합니다.")
        val visitOrder: Int,
        val memo: String?,
)
