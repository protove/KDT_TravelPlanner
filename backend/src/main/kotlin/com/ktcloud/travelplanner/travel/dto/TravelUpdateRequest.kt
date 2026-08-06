package com.ktcloud.travelplanner.travel.dto

import com.fasterxml.jackson.annotation.JsonProperty
import com.ktcloud.travelplanner.travel.model.CompanionType
import com.ktcloud.travelplanner.travel.model.TravelPurpose
import com.ktcloud.travelplanner.user.dto.PatchField
import jakarta.validation.Constraint
import jakarta.validation.ConstraintValidator
import jakarta.validation.ConstraintValidatorContext
import jakarta.validation.Payload
import jakarta.validation.constraints.PositiveOrZero
import java.time.LocalDate
import kotlin.reflect.KClass

@ValidTravelUpdate
data class TravelUpdateRequest(
        val title: PatchField<String> = PatchField.Absent,
        val startDate: PatchField<LocalDate> = PatchField.Absent,
        val endDate: PatchField<LocalDate> = PatchField.Absent,
        val countryId: PatchField<Short> = PatchField.Absent,
        val cityId: PatchField<Long> = PatchField.Absent,
        val companionType: PatchField<CompanionType> = PatchField.Absent,
        @JsonProperty("companionCount")
        val participantCount: PatchField<Int> = PatchField.Absent,
        val comment: PatchField<String> = PatchField.Absent,
        // 지정하면 기존 태그 목록을 통째로 교체함 (부분 추가/삭제 아님)
        val purposes: PatchField<Set<TravelPurpose>> = PatchField.Absent,
        @field:PositiveOrZero(message = "0 이상이어야 합니다.")
        val version: Long,
)

@Target(AnnotationTarget.CLASS)
@Retention(AnnotationRetention.RUNTIME)
@Constraint(validatedBy = [TravelUpdateValidator::class])
annotation class ValidTravelUpdate(
        val message: String = "플랜 수정값이 올바르지 않습니다.",
        val groups: Array<KClass<*>> = [],
        val payload: Array<KClass<out Payload>> = [],
)

class TravelUpdateValidator : ConstraintValidator<ValidTravelUpdate, TravelUpdateRequest> {
        override fun isValid(
                request: TravelUpdateRequest,
                context: ConstraintValidatorContext,
        ): Boolean {
                val violations = buildList {
                        validateRequiredText(request.title, "title", TITLE_MAX_LENGTH)
                        validateRequired(request.startDate, "startDate")
                        validateRequired(request.endDate, "endDate")
                        validatePositive(request.countryId, "countryId")
                        validatePositive(request.cityId, "cityId")
                        validateParticipantCount(request.participantCount)
                        validateRequired(request.purposes, "purposes")
                }
                if (violations.isEmpty()) {
                        return true
                }

                context.disableDefaultConstraintViolation()
                violations.forEach { (field, reason) ->
                        context.buildConstraintViolationWithTemplate(reason)
                                .addPropertyNode(field)
                                .addConstraintViolation()
                }
                return false
        }

        private fun MutableList<Pair<String, String>>.validateRequiredText(
                field: PatchField<String>,
                name: String,
                maxLength: Int,
        ) {
                val value = (field as? PatchField.Present)?.value ?: run {
                        if (field is PatchField.Present) add(name to "null일 수 없습니다.")
                        return
                }
                if (value.isBlank()) add(name to "비어 있을 수 없습니다.")
                if (value.length > maxLength) add(name to "${maxLength}자 이하여야 합니다.")
        }

        private fun <T> MutableList<Pair<String, String>>.validateRequired(
                field: PatchField<T>,
                name: String,
        ) {
                if (field is PatchField.Present && field.value == null) {
                        add(name to "null일 수 없습니다.")
                }
        }

        private fun <T : Number> MutableList<Pair<String, String>>.validatePositive(
                field: PatchField<T>,
                name: String,
        ) {
                val value = (field as? PatchField.Present)?.value ?: return
                if (value.toLong() <= 0) add(name to "양수여야 합니다.")
        }

        private fun MutableList<Pair<String, String>>.validateParticipantCount(field: PatchField<Int>) {
                val value = (field as? PatchField.Present)?.value ?: return
                if (value !in 1..Short.MAX_VALUE.toInt()) {
                        add("companionCount" to "1 이상 ${Short.MAX_VALUE} 이하여야 합니다.")
                }
        }

        companion object {
                private const val TITLE_MAX_LENGTH = 100
        }
}
