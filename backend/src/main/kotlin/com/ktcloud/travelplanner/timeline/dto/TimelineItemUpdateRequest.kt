package com.ktcloud.travelplanner.timeline.dto

import com.ktcloud.travelplanner.timeline.model.TimelineCategory
import com.ktcloud.travelplanner.user.dto.PatchField
import java.time.LocalDate

data class TimelineItemUpdateRequest(
	val dayNumber: PatchField<Int> = PatchField.Absent,
	val visitDate: PatchField<LocalDate> = PatchField.Absent,
	val cityId: PatchField<Long> = PatchField.Absent,
	val category: PatchField<TimelineCategory> = PatchField.Absent,
	val foodSubcategory: PatchField<String> = PatchField.Absent,
	val name: PatchField<String> = PatchField.Absent,
	val googlePlaceId: PatchField<String> = PatchField.Absent,
	val visitOrder: PatchField<Int> = PatchField.Absent,
	val memo: PatchField<String> = PatchField.Absent,
)
