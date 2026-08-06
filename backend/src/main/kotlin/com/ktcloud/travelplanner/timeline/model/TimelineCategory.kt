package com.ktcloud.travelplanner.timeline.model

import com.fasterxml.jackson.annotation.JsonCreator
import com.fasterxml.jackson.annotation.JsonValue

enum class TimelineCategory(
	private val apiValue: String,
) {
	ATTRACTION("관광지"),
	FOOD("음식"),
	ACCOMMODATION("숙소"),
	TRANSPORTATION("교통"),
	OTHER("기타"),
	;

	@JsonValue
	fun toApiValue(): String = apiValue

	companion object {
		@JvmStatic
		@JsonCreator
		fun fromApiValue(value: String): TimelineCategory =
			entries.firstOrNull { it.apiValue == value }
				?: throw IllegalArgumentException("Unsupported timeline category.")
	}
}
