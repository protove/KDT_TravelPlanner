package com.ktcloud.travelplanner.travel.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.location.model.City
import com.ktcloud.travelplanner.location.model.Country
import com.ktcloud.travelplanner.location.repository.CityRepository
import com.ktcloud.travelplanner.location.repository.CountryRepository
import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.model.TravelRole
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.model.TimelineItem
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.dto.TravelDetailResponse
import com.ktcloud.travelplanner.travel.dto.TravelUpdateRequest
import com.ktcloud.travelplanner.travel.model.PlannerPurpose
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.model.TravelPurpose
import com.ktcloud.travelplanner.travel.repository.PlannerPurposeRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import com.ktcloud.travelplanner.user.dto.PatchField
import org.springframework.dao.OptimisticLockingFailureException
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.LocalDate
import java.time.temporal.ChronoUnit
import java.util.UUID

@Service
class TravelUpdateService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val countryRepository: CountryRepository,
        private val cityRepository: CityRepository,
        private val timelineItemRepository: TimelineItemRepository,
        private val plannerPurposeRepository: PlannerPurposeRepository,
) {
        @Transactional
        fun updateTravel(
                travelId: UUID,
                requesterId: UUID,
                request: TravelUpdateRequest,
        ): TravelDetailResponse {
                val travel = travelRepository.findById(travelId).orElseThrow(::TravelUpdateNotFoundException)
                val permission = resolveWritePermission(travel, requesterId)
                if (travel.version != request.version) {
                        throw TravelVersionConflictException()
                }

                val startDate = request.startDate.resolveRequired(travel.startDate)
                val endDate = request.endDate.resolveRequired(travel.endDate)
                val country = resolveCountry(request.countryId, travel.country)
                val city = resolveCity(request.cityId, travel.city)
                val timelineItems = timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(travelId)
                validateTimelineDates(startDate, endDate, timelineItems)

                try {
                        travel.updateBasicInfo(
                                title = request.title.resolveRequired(travel.title).trim(),
                                startDate = startDate,
                                endDate = endDate,
                                country = country,
                                city = city,
                                companionType = request.companionType.resolveNullable(travel.companionType),
                                participantCount = request.participantCount.resolveNullable(travel.participantCount?.toInt())?.toShort(),
                                comment = request.comment.resolveNullable(travel.comment),
                        )
                        val savedTravel = travelRepository.saveAndFlush(travel)

                        // purposes는 Travel과 별개 Entity라 여기서 직접 갱신 (지정된 경우에만 전체 교체)
                        val purposes = if (request.purposes is PatchField.Present) {
                                val newPurposes = request.purposes.value
                                        ?: throw InvalidTravelUpdateException()
                                plannerPurposeRepository.deleteAllByTravelId(travelId)
                                plannerPurposeRepository.flush()
                                plannerPurposeRepository.saveAll(
                                        newPurposes.map { PlannerPurpose(travel = savedTravel, purpose = it) },
                                )
                                newPurposes
                        } else {
                                plannerPurposeRepository.findAllByTravelId(travelId).map { it.purpose }.toSet()
                        }

                        return TravelDetailResponse.from(savedTravel, permission, timelineItems, purposes)
                } catch (_: IllegalArgumentException) {
                        throw InvalidTravelUpdateException()
                } catch (_: OptimisticLockingFailureException) {
                        throw TravelVersionConflictException()
                }
        }

        private fun resolveWritePermission(
                travel: Travel,
                requesterId: UUID,
        ): TravelPermission {
                if (travel.owner.id == requesterId) {
                        return TravelPermission.OWNER
                }
                if (travelMemberRepository.findAcceptedRole(travel.id, requesterId) != TravelRole.READ_WRITE) {
                        throw TravelUpdateAccessDeniedException()
                }
                return TravelPermission.READ_WRITE
        }

        private fun resolveCountry(
                field: PatchField<Short>,
                current: Country?,
        ): Country? = when (field) {
                PatchField.Absent -> current
                is PatchField.Present -> field.value?.let { countryId ->
                        countryRepository.findByIdAndIsActiveTrue(countryId).orElseThrow(::TravelCountryNotFoundException)
                }
        }

        private fun resolveCity(
                field: PatchField<Long>,
                current: City?,
        ): City? = when (field) {
                PatchField.Absent -> current
                is PatchField.Present -> field.value?.let { cityId ->
                        cityRepository.findByIdAndIsActiveTrue(cityId).orElseThrow(::TravelCityNotFoundException)
                }
        }

        private fun validateTimelineDates(
                startDate: LocalDate,
                endDate: LocalDate,
                timelineItems: List<TimelineItem>,
        ) {
                // 미배정 항목(dayNumber, visitDate가 null)은 여행 기간 검증 대상이 아니므로 건너뜀
                val invalid = timelineItems.any { item ->
                        val visitDate = item.visitDate ?: return@any false
                        val dayNumber = item.dayNumber ?: return@any false
                        visitDate.isBefore(startDate) ||
                                visitDate.isAfter(endDate) ||
                                dayNumber.toLong() != ChronoUnit.DAYS.between(startDate, visitDate) + 1
                }
                if (invalid) {
                        throw TravelTimelineDateConflictException()
                }
        }

        private fun <T> PatchField<T>.resolveRequired(current: T): T = when (this) {
                PatchField.Absent -> current
                is PatchField.Present -> value ?: throw InvalidTravelUpdateException()
        }

        private fun <T> PatchField<T>.resolveNullable(current: T?): T? = when (this) {
                PatchField.Absent -> current
                is PatchField.Present -> value
        }
}

class TravelUpdateNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelCountryNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelCityNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TravelUpdateAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)

class InvalidTravelUpdateException : DomainException(ErrorCode.INVALID_REQUEST, "플랜 수정값이 올바르지않습니다.")

class TravelTimelineDateConflictException : DomainException(
        ErrorCode.CONFLICT,
        "변경할 여행 기간과 기존 타임라인 날짜가 충돌합니다.",
)

class TravelVersionConflictException : DomainException(ErrorCode.CONFLICT, "플랜이 다른 요청에 의해 변경되었습니다.")
