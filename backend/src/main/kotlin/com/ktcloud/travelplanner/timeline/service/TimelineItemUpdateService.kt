package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.dto.TimelineItemResponse
import com.ktcloud.travelplanner.timeline.dto.TimelineItemUpdateRequest
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.global.dto.PatchField
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TimelineItemUpdateService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val cityRepository: CityRepository,
        private val timelineItemRepository: TimelineItemRepository,
) {
        @Transactional
        fun updateTimelineItem(
                travelId: UUID,
                itemId: UUID,
                requesterId: UUID,
                request: TimelineItemUpdateRequest,
        ): TimelineItemResponse {
                val travel = travelRepository.findById(travelId).orElseThrow(::TimelineUpdateTravelNotFoundException)
                validateWritePermission(travel, requesterId)
                val item = timelineItemRepository.findByIdAndTravelId(itemId, travelId)
                        ?: throw TimelineItemNotFoundException()

                // dayNumber, visitDate는 "미배정 상태"를 표현할 수 있어야 하므로
                // 필수값(resolveRequired)이 아니라 null 허용(resolveNullable)으로 처리
                val dayNumber = request.dayNumber
                        .resolveNullable(item.dayNumber?.toInt())
                        ?.toShortChecked()
                val visitDate = request.visitDate.resolveNullable(item.visitDate)
                if ((dayNumber == null) != (visitDate == null)) {
                        throw InvalidTimelineItemUpdateException()
                }

                val visitOrder = request.visitOrder.resolveRequired(item.visitOrder.toInt()).toShortChecked()
                val city = resolveCity(request.cityId, item.city)
                val category = request.category.resolveRequired(item.category)
                val foodSubcategory = request.foodSubcategory.resolveOptionalText(item.foodSubcategory)
                val name = request.name.resolveRequired(item.name).trim()
                val googlePlaceId = request.googlePlaceId.resolveOptionalText(item.googlePlaceId)
                val memo = request.memo.resolveOptionalText(item.memo)

                // 미배정 상태(dayNumber == null)에서는 "같은 일차 내 순서 중복" 개념이 없으므로 검사하지 않음
                if (dayNumber != null &&
                        timelineItemRepository.existsByTravelIdAndDayNumberAndVisitOrderAndIdNot(
                                travelId,
                                dayNumber,
                                visitOrder,
                                itemId,
                        )
                ) {
                        throw TimelineItemOrderConflictException()
                }

                try {
                        item.updateDetails(
                                dayNumber = dayNumber,
                                visitDate = visitDate,
                                city = city,
                                category = category,
                                foodSubcategory = foodSubcategory,
                                name = name,
                                googlePlaceId = googlePlaceId,
                                visitOrder = visitOrder,
                                memo = memo,
                        )
                } catch (_: IllegalArgumentException) {
                        throw InvalidTimelineItemUpdateException()
                }

                val savedItem = try {
                        timelineItemRepository.saveAndFlush(item)
                } catch (_: DataIntegrityViolationException) {
                        throw TimelineItemOrderConflictException()
                }
                return TimelineItemResponse.from(savedItem)
        }

        private fun validateWritePermission(
                travel: Travel,
                requesterId: UUID,
        ) {
                if (travel.owner.id == requesterId) return
                if (!travelMemberRepository.existsAcceptedReadWriteMember(travel.id, requesterId)) {
                        throw TimelineItemUpdateAccessDeniedException()
                }
        }

        private fun resolveCity(
                field: PatchField<Long>,
                current: City?,
        ): City? = when (field) {
                PatchField.Absent -> current
                is PatchField.Present -> field.value?.let { cityId ->
                        cityRepository.findByIdAndIsActiveTrue(cityId).orElseThrow(::TimelineUpdateCityNotFoundException)
                }
        }

        private fun Int.toShortChecked(): Short {
                if (this !in 1..Short.MAX_VALUE.toInt()) throw InvalidTimelineItemUpdateException()
                return toShort()
        }

        private fun <T> PatchField<T>.resolveRequired(current: T): T = when (this) {
                PatchField.Absent -> current
                is PatchField.Present -> value ?: throw InvalidTimelineItemUpdateException()
        }

        private fun <T> PatchField<T>.resolveNullable(current: T?): T? = when (this) {
                PatchField.Absent -> current
                is PatchField.Present -> value
        }

        private fun PatchField<String>.resolveOptionalText(current: String?): String? =
                resolveNullable(current)?.trim()?.takeIf(String::isNotEmpty)
}

class TimelineUpdateTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineItemNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineUpdateCityNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineItemUpdateAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidTimelineItemUpdateException : DomainException(
        ErrorCode.INVALID_REQUEST,
        "타임라인 수정값이 올바르지않습니다.",
)

class TimelineItemOrderConflictException : DomainException(ErrorCode.CONFLICT, "같은 일차에 방문 순서가 중복됩니다.")
