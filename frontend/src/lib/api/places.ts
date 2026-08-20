import { apiFetch } from "@/lib/api/client";

/** 백엔드 PlaceSearchResultResponse.kt와 대응. Google Places 프록시 결과. */
export interface PlaceSearchResult {
  placeId: string;
  name: string;
  latitude: number;
  longitude: number;
  rating: number | null;
}

export interface NearbyPlaceSearchParams {
  latitude: number;
  longitude: number;
  radiusMeters?: number;
}

/** Google Place 검색. query/countryCode 둘 다 백엔드 필수 파라미터(PlaceSearchController). */
export async function searchPlaces(
  accessToken: string,
  query: string,
  countryCode: string,
): Promise<PlaceSearchResult[]> {
  const params = new URLSearchParams({ query, countryCode });
  return apiFetch<PlaceSearchResult[]>(`/api/v1/places/search?${params.toString()}`, accessToken);
}

export async function searchNearbyPlaces(
  accessToken: string,
  { latitude, longitude, radiusMeters }: NearbyPlaceSearchParams,
): Promise<PlaceSearchResult[]> {
  const params = new URLSearchParams({
    latitude: String(latitude),
    longitude: String(longitude),
  });

  if (radiusMeters !== undefined) {
    params.set("radiusMeters", String(radiusMeters));
  }

  return apiFetch<PlaceSearchResult[]>(`/api/v1/places/nearby?${params.toString()}`, accessToken);
}
