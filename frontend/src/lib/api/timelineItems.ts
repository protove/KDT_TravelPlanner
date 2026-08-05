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
