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

/** 백엔드 TravelService.VALID_SEARCH_SCOPES와 대응. */
export type TravelSearchScope = "ALL" | "TITLE" | "DESCRIPTION" | "DESTINATION";

export interface FetchTravelsParams {
  keyword?: string;
  searchScope?: TravelSearchScope;
  /** YYYY-MM-DD. 여행 "자체 기간"(startDate~endDate)이 이 구간과 겹치는지로 거른다. */
  periodStart?: string;
  periodEnd?: string;
  page?: number;
  size?: number;
}

/**
 * 현재 사용자가 소유하거나 참여 중인 여행 목록을 페이지 단위로 조회한다. keyword를 넘기면
 * searchScope(기본 ALL)에 따라 제목/설명/여행지(국가·도시명, 한글·영문)를 검색한다.
 */
export async function fetchTravels(
  accessToken: string,
  params: FetchTravelsParams = {},
): Promise<PageResponse<TravelSummary>> {
  const searchParams = new URLSearchParams();
  if (params.keyword) searchParams.set("keyword", params.keyword);
  if (params.searchScope) searchParams.set("searchScope", params.searchScope);
  if (params.periodStart) searchParams.set("periodStart", params.periodStart);
  if (params.periodEnd) searchParams.set("periodEnd", params.periodEnd);
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

/** 백엔드 TimelineCategory.kt와 대응. @JsonValue로 한글 문자열로 직렬화된다. */
export type TimelineCategory = "관광지" | "음식" | "숙소" | "교통" | "기타";

/** 백엔드 TimelineItemResponse.kt와 대응. */
export interface TimelineItem {
  timelineItemId: string;
  dayNumber: number | null;
  visitDate: string | null;
  cityId: number | null;
  category: TimelineCategory;
  foodSubcategory: string | null;
  name: string;
  googlePlaceId: string | null;
  visitOrder: number;
  memo: string | null;
}

/** 백엔드 TravelDetailResponse.kt와 대응. 멤버/댓글은 아직 프론트에서 안 씀. */
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
  timelineItems: TimelineItem[];
}

/** 여행 상세를 조회한다. 없는 id면 404, 접근 권한 없으면 403. */
export async function fetchTravelDetail(accessToken: string, travelId: string): Promise<TravelDetail> {
  return apiFetch<TravelDetail>(`/api/v1/travels/${travelId}`, accessToken);
}

/**
 * 백엔드 TravelUpdateRequest.kt와 대응. PatchField 방식이라 바뀐 키만 담아 보내면 된다
 * (키를 아예 안 넣으면 해당 필드는 그대로 유지). version은 낙관적 락이라 항상 필수.
 */
export interface TravelUpdatePatch {
  title?: string;
  startDate?: string;
  endDate?: string;
  countryId?: number | null;
  cityId?: number | null;
  companionType?: CompanionType;
  companionCount?: number;
  comment?: string | null;
  version: number;
}

/** 여행 기본정보를 부분 수정한다. version 충돌 시 409(ApiError)가 던져진다. */
export async function updateTravel(
  accessToken: string,
  travelId: string,
  patch: TravelUpdatePatch,
): Promise<TravelDetail> {
  return apiFetch<TravelDetail>(`/api/v1/travels/${travelId}`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** 여행을 삭제한다. OWNER만 가능. */
export async function deleteTravel(accessToken: string, travelId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}`, accessToken, { method: "DELETE" });
}
