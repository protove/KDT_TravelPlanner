import { apiFetch } from "@/lib/api/client";
import type { TravelRole } from "@/lib/api/permission";

export interface CreateInvitationRequest {
  nickname: string;
  role: TravelRole;
}

export interface CreateInvitationResponse {
  invitationId: string;
}

/** 정확한 닉네임으로 초대를 생성한다. 닉네임 검색/자동완성 API는 없다. */
export async function createInvitation(
  accessToken: string,
  travelId: string,
  request: CreateInvitationRequest,
): Promise<CreateInvitationResponse> {
  return apiFetch<CreateInvitationResponse>(`/api/v1/travels/${travelId}/invitations`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** 발송한(대기 중인) 초대를 취소한다. */
export async function cancelInvitation(
  accessToken: string,
  travelId: string,
  invitationId: string,
): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}/invitations/${invitationId}`, accessToken, {
    method: "DELETE",
  });
}
