package com.ktcloud.travelplanner.user.dto

import com.ktcloud.travelplanner.user.model.Gender
import jakarta.validation.Constraint
import jakarta.validation.ConstraintValidator
import jakarta.validation.ConstraintValidatorContext
import jakarta.validation.Payload
import kotlin.reflect.KClass

@ValidUserProfileUpdate
data class UserProfileUpdateRequest(
	val nickname: PatchField<String> = PatchField.Absent,
	val profileImageUrl: PatchField<String> = PatchField.Absent,
	val gender: PatchField<Gender> = PatchField.Absent,
	val birthYear: PatchField<Int> = PatchField.Absent,
)

@Target(AnnotationTarget.CLASS)
@Retention(AnnotationRetention.RUNTIME)
@Constraint(validatedBy = [UserProfileUpdateValidator::class])
annotation class ValidUserProfileUpdate(
	val message: String = "프로필 수정값이 올바르지 않습니다.",
	val groups: Array<KClass<*>> = [],
	val payload: Array<KClass<out Payload>> = [],
)

class UserProfileUpdateValidator : ConstraintValidator<ValidUserProfileUpdate, UserProfileUpdateRequest> {
	override fun isValid(
		request: UserProfileUpdateRequest,
		context: ConstraintValidatorContext,
	): Boolean {
		val violations = buildList {
			val profileImageUrl = (request.profileImageUrl as? PatchField.Present)?.value
			if (profileImageUrl != null) {
				add("profileImageUrl" to "프로필 이미지 업로드 완료 API를 사용해야 합니다.")
			}

			val nickname = (request.nickname as? PatchField.Present)?.value
			if (nickname != null && nickname.isBlank()) {
				add("nickname" to "비어 있을 수 없습니다.")
			}
			if (nickname != null && nickname.length > NICKNAME_MAX_LENGTH) {
				add("nickname" to "${NICKNAME_MAX_LENGTH}자 이하여야 합니다.")
			}

			val birthYear = (request.birthYear as? PatchField.Present)?.value
			if (birthYear != null && birthYear !in MIN_BIRTH_YEAR..MAX_BIRTH_YEAR) {
				add("birthYear" to "$MIN_BIRTH_YEAR 이상 $MAX_BIRTH_YEAR 이하여야 합니다.")
			}
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

	companion object {
		private const val NICKNAME_MAX_LENGTH = 30
		private const val MIN_BIRTH_YEAR = 1900
		private const val MAX_BIRTH_YEAR = 2100
	}
}
