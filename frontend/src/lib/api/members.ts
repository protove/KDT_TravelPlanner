import { apiFetch } from "@/lib/api/client";
import type { TravelPermission, TravelRole } from "@/lib/api/permission";

/** 백엔드 InvitationStatus.kt와 대응 (REJECTED 멤버는 목록에 내려오지 않는다). */
export type InvitationStatus = "ACCEPTED" | "PENDING";

/** 백엔드 TravelMemberResponse.kt와 대응. */
export interface TravelMember {
  userId: string;
  nickname: string | null;
  profileImageUrl: string | null;
  role: TravelPermission;
  isOwner: boolean;
  status: InvitationStatus;
  /** PENDING 멤버를 초대 취소(cancelInvitation)할 때 필요. 오너는 null. */
  invitationId: string | null;
}

/** 여행 멤버 목록을 조회한다(OWNER 포함). */
export async function fetchTravelMembers(accessToken: string, travelId: string): Promise<TravelMember[]> {
  return apiFetch<TravelMember[]>(`/api/v1/travels/${travelId}/members`, accessToken);
}

/** 멤버의 권한을 변경한다. OWNER는 대상이 될 수 없다. */
export async function updateMemberRole(
  accessToken: string,
  travelId: string,
  memberId: string,
  role: TravelRole,
): Promise<TravelMember> {
  return apiFetch<TravelMember>(`/api/v1/travels/${travelId}/members/${memberId}`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
}

/** 멤버를 여행에서 추방한다. */
export async function removeMember(accessToken: string, travelId: string, memberId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}/members/${memberId}`, accessToken, { method: "DELETE" });
}

/** 내가 이 여행에서 나간다. */
export async function leaveTravel(accessToken: string, travelId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}/members/me`, accessToken, { method: "DELETE" });
}
