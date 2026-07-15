package com.ktcloud.travelplanner.user.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.user.dto.UserProfileResponse
import com.ktcloud.travelplanner.user.repository.UserRepository
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
}

class UserNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)
