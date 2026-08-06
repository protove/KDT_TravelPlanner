package com.ktcloud.travelplanner.travel.dto

import jakarta.validation.Constraint
import jakarta.validation.ConstraintValidator
import jakarta.validation.ConstraintValidatorContext
import jakarta.validation.Payload
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size
import java.time.LocalDate
import kotlin.reflect.KClass

@ValidTravelDateRange
data class TravelCreateRequest(
	@field:NotBlank(message = "비어 있을 수 없습니다.")
	@field:Size(max = 100, message = "100자 이하여야 합니다.")
	val title: String,
	val startDate: LocalDate,
	val endDate: LocalDate,
)

@Target(AnnotationTarget.CLASS)
@Retention(AnnotationRetention.RUNTIME)
@Constraint(validatedBy = [TravelDateRangeValidator::class])
annotation class ValidTravelDateRange(
	val message: String = "종료일은 시작일보다 빠를 수 없습니다.",
	val groups: Array<KClass<*>> = [],
	val payload: Array<KClass<out Payload>> = [],
)

class TravelDateRangeValidator : ConstraintValidator<ValidTravelDateRange, TravelCreateRequest> {
	override fun isValid(
		request: TravelCreateRequest,
		context: ConstraintValidatorContext,
	): Boolean {
		if (!request.endDate.isBefore(request.startDate)) {
			return true
		}

		context.disableDefaultConstraintViolation()
		context.buildConstraintViolationWithTemplate("종료일은 시작일보다 빠를 수 없습니다.")
			.addPropertyNode("endDate")
			.addConstraintViolation()
		return false
	}
}
