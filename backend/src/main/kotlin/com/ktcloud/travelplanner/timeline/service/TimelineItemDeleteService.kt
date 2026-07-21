package com.ktcloud.travelplanner.timeline.service

import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID

@Service
class TimelineItemDeleteService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val timelineItemRepository: TimelineItemRepository,
) {
        @Transactional
        fun deleteTimelineItem(
                travelId: UUID,
                itemId: UUID,
                requesterId: UUID,
        ) {
                val travel = travelRepository.findById(travelId).orElseThrow(::TimelineDeleteTravelNotFoundException)
                if (travel.isDeleted) throw TimelineDeleteTravelNotFoundException()
                validateWritePermission(travel, requesterId)
                val item = timelineItemRepository.findByIdAndTravelId(itemId, travelId)
                        ?: throw TimelineDeleteItemNotFoundException()
                // 미배정 상태(dayNumber == null)인 항목은 "같은 일차 내 순서 압축" 대상이 아니므로
                // 순서를 당겨줄 뒤 항목 조회 자체를 건너뜀
                val dayNumber = item.dayNumber
                val laterItems = if (dayNumber != null) {
                        timelineItemRepository.findItemsAfterVisitOrder(
                                travelId,
                                dayNumber,
                                item.visitOrder,
                        )
                } else {
                        emptyList()
                }

                timelineItemRepository.delete(item)
                timelineItemRepository.flush()
                laterItems.forEach { laterItem ->
                        laterItem.moveVisitOrderEarlier()
                        timelineItemRepository.saveAndFlush(laterItem)
                }
        }

        private fun validateWritePermission(
                travel: Travel,
                requesterId: UUID,
        ) {
                if (travel.owner.id == requesterId) return
                if (!travelMemberRepository.existsAcceptedReadWriteMember(travel.id, requesterId)) {
                        throw TimelineItemDeleteAccessDeniedException()
                }
        }
}

class TimelineDeleteTravelNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineDeleteItemNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)

class TimelineItemDeleteAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)
