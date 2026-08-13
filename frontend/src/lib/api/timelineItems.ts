import { apiFetch } from "@/lib/api/client";
import type { TimelineCategory, TimelineItem } from "@/lib/api/travel";

/** 백엔드 TimelineItemCreateRequest.kt와 대응. */
export interface CreateTimelineItemRequest {
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

export interface CreateTimelineItemResponse {
  timelineItemId: string;
}

export async function createTimelineItem(
  accessToken: string,
  travelId: string,
  request: CreateTimelineItemRequest,
): Promise<CreateTimelineItemResponse> {
  return apiFetch<CreateTimelineItemResponse>(`/api/v1/travels/${travelId}/timeline-items`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** 백엔드 TimelineItemUpdateRequest.kt와 대응(PatchField). 바뀐 키만 담아 보낸다. */
export interface TimelineItemUpdatePatch {
  dayNumber?: number | null;
  visitDate?: string | null;
  cityId?: number | null;
  category?: TimelineCategory;
  foodSubcategory?: string | null;
  name?: string;
  googlePlaceId?: string | null;
  visitOrder?: number;
  memo?: string | null;
}

export async function updateTimelineItem(
  accessToken: string,
  travelId: string,
  itemId: string,
  patch: TimelineItemUpdatePatch,
): Promise<TimelineItem> {
  return apiFetch<TimelineItem>(`/api/v1/travels/${travelId}/timeline-items/${itemId}`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function deleteTimelineItem(accessToken: string, travelId: string, itemId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}/timeline-items/${itemId}`, accessToken, { method: "DELETE" });
}

/** 백엔드 TimelineItemOrderUpdate.kt와 대응. */
export interface TimelineItemOrderUpdateItem {
  itemId: string;
  visitOrder: number;
}

/**
 * 같은 날짜(dayNumber) 안에서 카드 순서만 바뀐 경우 전용 엔드포인트.
 * 개별 항목을 하나씩 PATCH로 순서를 바꾸면(updateTimelineItem 반복 호출) 예를 들어 A를 2번으로 옮기는
 * 순간 원래 2번이던 B와 잠깐 겹쳐서 409(TimelineItemOrderConflictException, "같은 일차에 방문 순서가
 * 중복됩니다")가 난다. 백엔드가 임시 순번을 거쳐 스왑하는 방식으로 이 문제를 안전하게 처리해주므로,
 * 해당 날짜에 있는 "전체" 항목의 목표 순서를 한 번에 같이 보내야 한다(일부만 보내면 400).
 */
export async function updateTimelineItemOrder(
  accessToken: string,
  travelId: string,
  dayNumber: number,
  items: TimelineItemOrderUpdateItem[],
): Promise<void> {
  await apiFetch<void>(`/api/v1/travels/${travelId}/timeline-items/order`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dayNumber, items }),
  });
}
