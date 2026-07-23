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
