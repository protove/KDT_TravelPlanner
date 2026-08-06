package com.ktcloud.travelplanner.travel.service
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode
import com.ktcloud.travelplanner.membership.model.TravelPermission
import com.ktcloud.travelplanner.membership.repository.TravelMemberRepository
import com.ktcloud.travelplanner.timeline.repository.TimelineItemRepository
import com.ktcloud.travelplanner.travel.dto.TravelDetailResponse
import com.ktcloud.travelplanner.travel.model.Travel
import com.ktcloud.travelplanner.travel.repository.PlannerPurposeRepository
import com.ktcloud.travelplanner.travel.repository.TravelRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.util.UUID
@Service
class TravelDetailService(
        private val travelRepository: TravelRepository,
        private val travelMemberRepository: TravelMemberRepository,
        private val timelineItemRepository: TimelineItemRepository,
        private val plannerPurposeRepository: PlannerPurposeRepository,
) {
        @Transactional(readOnly = true)
        fun getTravelDetail(
                travelId: UUID,
                requesterId: UUID,
        ): TravelDetailResponse {
                val travel = travelRepository.findById(travelId).orElseThrow(::TravelDetailNotFoundException)
                val permission = resolvePermission(travel, requesterId)
                val timelineItems = timelineItemRepository.findAllByTravelIdOrderByDayNumberAscVisitOrderAsc(travelId)
                val purposes = plannerPurposeRepository.findAllByTravelId(travelId).map { it.purpose }.toSet()
                return TravelDetailResponse.from(travel, permission, timelineItems, purposes)
        }
        private fun resolvePermission(
                travel: Travel,
                requesterId: UUID,
        ): TravelPermission {
                if (travel.owner.id == requesterId) {
                        return TravelPermission.OWNER
                }
                val role = travelMemberRepository.findAcceptedRole(travel.id, requesterId)
                        ?: throw TravelDetailAccessDeniedException()
                return TravelPermission.valueOf(role.name)
        }
}
class TravelDetailNotFoundException : DomainException(ErrorCode.RESOURCE_NOT_FOUND)
class TravelDetailAccessDeniedException : DomainException(ErrorCode.ACCESS_DENIED)
