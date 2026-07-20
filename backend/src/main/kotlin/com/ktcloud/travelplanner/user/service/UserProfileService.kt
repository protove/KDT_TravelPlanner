package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.dto.PatchField
import com.ktcloud.travelplanner.user.dto.UserProfileResponse
import com.ktcloud.travelplanner.user.dto.UserProfileUpdateRequest
import com.ktcloud.travelplanner.user.repository.UserRepository
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class UserProfileService(
	private val userRepository: UserRepository,
) {
	@Transactional(readOnly = true)
	fun getProfile(userId: UUID): UserProfileResponse {
		val user = userRepository.findById(userId)
			.orElseThrow(::UserNotFoundException)
		return UserProfileResponse.from(user)
	}

	@Transactional
	fun updateProfile(
		userId: UUID,
		request: UserProfileUpdateRequest,
	): UserProfileResponse {
		val user = userRepository.findById(userId)
			.orElseThrow(::UserNotFoundException)
		val nickname = request.nickname.resolve(user.nickname)

		if (nickname != null && nickname != user.nickname && userRepository.existsByNickname(nickname)) {
			throw DuplicateNicknameException()
		}

		user.updateProfile(
			nickname = nickname,
			profileImageUrl = request.profileImageUrl.resolve(user.profileImageUrl),
			gender = request.gender.resolve(user.gender),
			birthYear = request.birthYear.resolve(user.birthYear?.toInt()),
		)

		return try {
			UserProfileResponse.from(userRepository.saveAndFlush(user))
		} catch (exception: DataIntegrityViolationException) {
			throw DuplicateNicknameException(exception)
		}
	}

	private fun <T> PatchField<T>.resolve(currentValue: T?): T? = when (this) {
		PatchField.Absent -> currentValue
		is PatchField.Present -> value
	}
}

class UserNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class DuplicateNicknameException(
	cause: Throwable? = null,
) : DomainException(ErrorCode.CONFLICT, "이미 사용 중인 닉네임입니다.") {
	init {
		if (cause != null) {
			initCause(cause)
		}
	}
}
