import { apiFetch } from "@/lib/api/client";

/** 백엔드 CountryResponse.kt와 대응. */
export interface Country {
  countryId: number;
  code: string;
  nameKo: string;
  nameEn: string;
}

/** 백엔드 CityResponse.kt와 대응. */
export interface City {
  cityId: number;
  countryId: number;
  nameKo: string;
  nameEn: string;
  googlePlaceId: string | null;
  latitude: number | null;
  longitude: number | null;
}

/** 국가 전체 목록(카탈로그, 검색 아님)을 조회한다. */
export async function fetchCountries(accessToken: string): Promise<Country[]> {
  return apiFetch<Country[]>("/api/v1/countries", accessToken);
}

/** 특정 국가에 속한 도시 목록을 조회한다. */
export async function fetchCitiesByCountry(accessToken: string, countryId: number): Promise<City[]> {
  return apiFetch<City[]>(`/api/v1/countries/${countryId}/cities`, accessToken);
}
