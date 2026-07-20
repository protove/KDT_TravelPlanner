package com.ktcloud.travelplanner.global.response

data class ApiResponse<T> private constructor(
	val data: T,
) {
	companion object {
		fun <T> success(data: T): ApiResponse<T> = ApiResponse(data)
	}
}
