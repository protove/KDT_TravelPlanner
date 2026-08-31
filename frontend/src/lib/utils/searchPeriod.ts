export type SearchPeriodPreset = "ALL" | "1M" | "3M" | "6M" | "1Y";

export const SEARCH_PERIOD_OPTIONS: { value: SearchPeriodPreset; label: string }[] = [
  { value: "1M", label: "최근 1개월" },
  { value: "3M", label: "최근 3개월" },
  { value: "6M", label: "최근 6개월" },
  { value: "1Y", label: "최근 1년" },
  { value: "ALL", label: "전체 기간" },
];

/** 기본값은 "전체 기간으로 조회하는 불상사"를 피하기 위해 무제한(ALL)이 아닌 최근 3개월로 좁힌다. */
export const DEFAULT_SEARCH_PERIOD: SearchPeriodPreset = "3M";

function toDateOnly(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** preset을 오늘 기준 [periodStart, periodEnd] YYYY-MM-DD 문자열로 변환한다. ALL이면 둘 다 undefined(필터 없음). */
export function resolveSearchPeriod(
  preset: SearchPeriodPreset,
  now: Date = new Date(),
): { periodStart?: string; periodEnd?: string } {
  if (preset === "ALL") return {};

  const start = new Date(now);
  if (preset === "1M") start.setMonth(start.getMonth() - 1);
  else if (preset === "3M") start.setMonth(start.getMonth() - 3);
  else if (preset === "6M") start.setMonth(start.getMonth() - 6);
  else if (preset === "1Y") start.setFullYear(start.getFullYear() - 1);

  return { periodStart: toDateOnly(start), periodEnd: toDateOnly(now) };
}
