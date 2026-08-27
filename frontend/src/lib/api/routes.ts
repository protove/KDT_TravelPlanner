import { apiFetch } from "@/lib/api/client";

/*
 * 기존 GET /routes 전용.
 */
export type TransportationType =
  | "DRIVE"
  | "WALK"
  | "BICYCLE";

/*
 * SCRUM-56 Preview 경로는
 * 한국에서 실제 동작 확인된 TRANSIT을 사용한다.
 */
export type TravelRoutePreviewTransportationType =
  "TRANSIT";

export interface TravelRouteLeg {
  fromTimelineItemId: string;
  toTimelineItemId: string;
  distanceMeters: number;
  durationSeconds: number;
}

export interface TravelRouteResponse {
  travelId: string;
  dayNumber: number;
  transportationType: TransportationType;
  encodedPolyline: string | null;
  totalDistanceMeters: number;
  totalDurationSeconds: number;
  legs: TravelRouteLeg[];
  warnings: string[];
}

export interface TravelRoutePreviewWaypoint {
  googlePlaceId: string;
  latitude: number;
  longitude: number;
}

export interface TravelRoutePreviewRequest {
  dayNumber: number;
  transportationType:
    TravelRoutePreviewTransportationType;
  waypoints: TravelRoutePreviewWaypoint[];
}

export interface TravelRoutePreviewResponse {
  dayNumber: number;

  transportationType:
    TravelRoutePreviewTransportationType;

  /*
   * 한 구간일 때의 하위 호환 값.
   */
  encodedPolyline: string | null;

  /*
   * A→B / B→C / C→D 구간별 경로.
   */
  encodedPolylines: string[];

  totalDistanceMeters: number;
  totalDurationSeconds: number;
  warnings: string[];
}

export async function getTravelRoute(
  accessToken: string,
  travelId: string,
  dayNumber: number,
  transportationType: TransportationType
): Promise<TravelRouteResponse> {
  const params =
    new URLSearchParams({
      dayNumber:
        String(dayNumber),

      transportationType,
    });

  return apiFetch<TravelRouteResponse>(
    `/api/v1/travels/${travelId}/routes?${params.toString()}`,
    accessToken
  );
}

export async function previewTravelRoute(
  accessToken: string,
  travelId: string,
  request: TravelRoutePreviewRequest
): Promise<TravelRoutePreviewResponse> {
  return apiFetch<TravelRoutePreviewResponse>(
    `/api/v1/travels/${travelId}/routes/preview`,
    accessToken,
    {
      method:
        "POST",

      headers: {
        "Content-Type":
          "application/json",
      },

      body:
        JSON.stringify(
          request
        ),
    }
  );
}