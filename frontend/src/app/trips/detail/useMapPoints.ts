import * as React from "react";
import { fetchTravelMapPoints, type TravelMapPoint } from "@/lib/api/mapPoints";

/**
 * 활성 날짜(dayNumber)에 배정된 일정 항목들의 실제 좌표(위도/경도)를 서버에서 불러온다.
 *
 * 주의: 이건 "정보 수정" 중의 로컬 draft(draftTimelineItems)가 아니라 서버에 실제
 * 저장된 상태를 기준으로 조회한다 — 그래서 예를 들어 날짜를 바꿔서 화면(일차 탭)에는
 * 바로 반영돼도, 지도 마커는 상단 "저장"을 눌러 서버에 반영된 뒤에야 새 위치로 옮겨간다.
 * refreshKey에 detail?.timelineItems처럼 저장 성공 후 바뀌는 값을 넘기면 그 시점에 다시 불러온다.
 */
export function useMapPoints(
  accessToken: string | null,
  travelId: string | undefined,
  dayNumber: number,
  refreshKey: unknown,
) {
  const [points, setPoints] = React.useState<TravelMapPoint[]>([]);

  React.useEffect(() => {
    if (!accessToken || !travelId) return;

    let cancelled = false;
    fetchTravelMapPoints(accessToken, travelId, dayNumber)
      .then((res) => {
        if (!cancelled) setPoints(res.points);
      })
      .catch(() => {
        if (!cancelled) setPoints([]);
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken, travelId, dayNumber, refreshKey]);

  return accessToken && travelId ? points : [];
}
