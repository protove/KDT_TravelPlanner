import { apiFetch } from "@/lib/api/client";

export interface TravelSummary {
  travelId: string;
  title: string;
  startDate: string;
  endDate: string;
  countryId: number | null;
  cityId: number | null;
  participantCount: number | null;
  permission: "OWNER" | "READ_ONLY" | "READ_WRITE";
  updatedAt: string;
}

export interface PageResponse<T> {
  content: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
  isFirst: boolean;
  isLast: boolean;
}

export interface FetchTravelsParams {
  keyword?: string;
  page?: number;
  size?: number;
}

/** 현재 사용자가 소유하거나 참여 중인 여행 목록을 페이지 단위로 조회한다. keyword를 넘기면 제목으로 검색한다. */
export async function fetchTravels(
  accessToken: string,
  params: FetchTravelsParams = {},
): Promise<PageResponse<TravelSummary>> {
  const searchParams = new URLSearchParams();
  if (params.keyword) searchParams.set("keyword", params.keyword);
  if (params.page != null) searchParams.set("page", String(params.page));
  if (params.size != null) searchParams.set("size", String(params.size));
  const qs = searchParams.toString();
  return apiFetch<PageResponse<TravelSummary>>(`/api/v1/travels${qs ? `?${qs}` : ""}`, accessToken);
}

/** 백엔드 TravelCreateRequest.kt와 대응. 생성 시점엔 제목/기간만 받는다. */
export interface TravelCreateRequest {
  title: string;
  startDate: string;
  endDate: string;
}

export interface TravelCreateResponse {
  travelId: string;
}

/** 여행을 새로 만든다. 국가/도시/동행/목적 등은 이후 PATCH로 채운다. */
export async function createTravel(
  accessToken: string,
  request: TravelCreateRequest,
): Promise<TravelCreateResponse> {
  return apiFetch<TravelCreateResponse>("/api/v1/travels", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export type CompanionType = "SOLO" | "COUPLE" | "FAMILY" | "FRIEND" | "PET" | "ETC";

/** 백엔드 TravelDetailResponse.kt와 대응. timelineItems/멤버/댓글은 아직 프론트에서 안 씀. */
export interface TravelDetail {
  travelId: string;
  ownerId: string;
  title: string;
  startDate: string;
  endDate: string;
  travelDays: number;
  countryId: number | null;
  cityId: number | null;
  companionType: CompanionType | null;
  participantCount: number | null;
  comment: string | null;
  version: number;
  permission: "OWNER" | "READ_ONLY" | "READ_WRITE";
}

/** 여행 상세를 조회한다. 없는 id면 404, 접근 권한 없으면 403. */
export async function fetchTravelDetail(accessToken: string, travelId: string): Promise<TravelDetail> {
  return apiFetch<TravelDetail>(`/api/v1/travels/${travelId}`, accessToken);
}
