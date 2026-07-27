import { apiFetch } from "@/lib/api/client";

/** 백엔드 TravelMapPointResponse.kt와 대응. googlePlaceId가 연결된 일정 항목 하나의 실제 좌표. */
export interface TravelMapPoint {
  timelineItemId: string;
  visitOrder: number;
  name: string;
  googlePlaceId: string;
  latitude: number;
  longitude: number;
}

/**
 * 백엔드 TravelMapPointsResponse.kt와 대응.
 * unmappedTimelineItemIds: googlePlaceId 자체가 없어서 좌표를 조회할 수 없는 항목.
 * unresolvedTimelineItemIds: googlePlaceId는 있는데 Google Place Details 조회가 실패한 항목.
 */
export interface TravelMapPoints {
  travelId: string;
  dayNumber: number;
  points: TravelMapPoint[];
  unmappedTimelineItemIds: string[];
  unresolvedTimelineItemIds: string[];
}

/** 특정 날짜(dayNumber)에 배정된 일정 항목들의 실제 위도/경도를 조회한다. */
export async function fetchTravelMapPoints(
  accessToken: string,
  travelId: string,
  dayNumber: number,
): Promise<TravelMapPoints> {
  const params = new URLSearchParams({ dayNumber: String(dayNumber) });
  return apiFetch<TravelMapPoints>(`/api/v1/travels/${travelId}/map-points?${params.toString()}`, accessToken);
}
