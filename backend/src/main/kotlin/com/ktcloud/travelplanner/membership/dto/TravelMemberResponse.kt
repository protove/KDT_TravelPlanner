package com.ktcloud.travelplanner.membership.dto
import com.ktcloud.travelplanner.membership.model.InvitationStatus
import com.ktcloud.travelplanner.membership.model.TravelMember
import com.ktcloud.travelplanner.membership.model.TravelPermission
import java.util.UUID
data class TravelMemberResponse(
        val userId: UUID,
        val nickname: String?,
        val profileImageUrl: String?,
        val role: TravelPermission,
        val isOwner: Boolean,
        val status: InvitationStatus,
        // 이슈 #232 — PENDING 멤버는 초대 취소(DELETE /invitations/{invitationId})로만 제거할 수 있고,
        // 그 API는 TravelMember row 자체의 id를 요구한다. 오너는 초대 row가 없어 null.
        val invitationId: UUID?,
) {
        companion object {
                // 이슈 #150 — User 엔티티(travel.owner)를 직접 안 건드리고 값만 받도록 변경.
                // travel.owner.nickname처럼 프로퍼티를 직접 읽으면 @SQLRestriction 때문에
                // 탈퇴한 오너일 때 예외가 날 수 있어서, 호출부(TravelMemberQueryService)에서
                // 우회 조회한 값을 그대로 넘겨받는 방식으로 바꿈.
                fun fromOwner(
                        ownerId: UUID,
                        nickname: String?,
                        profileImageUrl: String?,
                ): TravelMemberResponse = TravelMemberResponse(
                        userId = ownerId,
                        nickname = nickname,
                        profileImageUrl = profileImageUrl,
                        role = TravelPermission.OWNER,
                        isOwner = true,
                        // 오너는 초대 개념이 없어 항상 ACCEPTED로 취급한다.
                        status = InvitationStatus.ACCEPTED,
                        invitationId = null,
                )
                fun fromMember(member: TravelMember): TravelMemberResponse = TravelMemberResponse(
                        userId = requireNotNull(member.user.id),
                        nickname = member.user.nickname,
                        profileImageUrl = member.user.profileImageUrl,
                        role = TravelPermission.valueOf(member.role.name),
                        isOwner = false,
                        status = member.status,
                        invitationId = member.id,
                )
        }
}
