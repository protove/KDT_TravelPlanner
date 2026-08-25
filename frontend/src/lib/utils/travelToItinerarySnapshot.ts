import { fetchTravelMapPoints } from "@/lib/api/mapPoints";
import type { TimelineItem, TravelDetail } from "@/lib/api/travel";
import type { ItinerarySnapshot, ItinerarySnapshotDay, ItinerarySnapshotItem } from "@/lib/types/community";

function groupByDayNumber(items: TimelineItem[]): Map<number, TimelineItem[]> {
  const map = new Map<number, TimelineItem[]>();
  for (const item of items) {
    if (item.dayNumber == null) continue;
    const group = map.get(item.dayNumber);
    if (group) {
      group.push(item);
    } else {
      map.set(item.dayNumber, [item]);
    }
  }
  return map;
}

/**
 * 여행 상세(TravelDetail)를 커뮤니티 게시글의 일정 스냅샷(ItinerarySnapshot)으로 변환한다.
 * travelToBodyJson과 달리 Tiptap 문서로 바꾸지 않고 일정 자체의 원래 모양(day별 장소 목록)을
 * 그대로 유지하며, day마다 /map-points를 호출해 좌표까지 이 시점 값으로 얼려서 함께 담는다 —
 * 그래야 이후 원본 여행이 바뀌거나, 그 여행에 권한이 없는 방문자가 게시글을 봐도 지도가 그대로 뜬다
 * (docs 미반영, 2026-08-25 결정: [[project_community_itinerary_snapshot]] 참고).
 *
 * dayNumber가 없는(미배정) 항목도 제외하지 않고 snapshot.unassigned에 따로 담는다 — day가
 * 없어 좌표(/map-points)는 못 구하므로 이 목록엔 lat/lng가 항상 비어있다.
 */
export async function travelToItinerarySnapshot(
  accessToken: string,
  travel: TravelDetail,
): Promise<ItinerarySnapshot> {
  const itemsByDay = groupByDayNumber(travel.timelineItems);
  const dayGroups = Array.from(itemsByDay.entries()).sort(([a], [b]) => a - b);

  const days: ItinerarySnapshotDay[] = await Promise.all(
    dayGroups.map(async ([dayNumber, items]) => {
      const dayItems = [...items].sort((a, b) => a.visitOrder - b.visitOrder);
      const visitDate = dayItems.find((item) => item.visitDate != null)?.visitDate ?? null;

      // 좌표 조회는 구글 Place Details를 거치는 라이브 호출이라 실패할 수 있다(장소가 사라졌거나
      // googlePlaceId 자체가 없는 등) — 실패해도 목록 자체는 스냅샷에 포함하고, 해당 day는 지도에
      // 마커 없이(빈 지도) 표시되게 한다.
      const points = await fetchTravelMapPoints(accessToken, travel.travelId, dayNumber).catch(() => null);
      const pointByItemId = new Map((points?.points ?? []).map((p) => [p.timelineItemId, p]));

      const snapshotItems: ItinerarySnapshotItem[] = dayItems.map((item) => {
        const point = pointByItemId.get(item.timelineItemId);
        return {
          timelineItemId: item.timelineItemId,
          name: item.name,
          category: item.category,
          foodSubcategory: item.foodSubcategory,
          visitOrder: item.visitOrder,
          lat: point?.latitude,
          lng: point?.longitude,
        };
      });

      return { dayNumber, visitDate, items: snapshotItems };
    }),
  );

  const unassigned: ItinerarySnapshotItem[] = travel.timelineItems
    .filter((item) => item.dayNumber == null)
    .sort((a, b) => a.visitOrder - b.visitOrder)
    .map((item) => ({
      timelineItemId: item.timelineItemId,
      name: item.name,
      category: item.category,
      foodSubcategory: item.foodSubcategory,
      visitOrder: item.visitOrder,
      // day가 없어 /map-points로 좌표를 조회할 방법이 없다 — lat/lng는 항상 비워둔다.
    }));

  return {
    title: travel.title,
    startDate: travel.startDate,
    endDate: travel.endDate,
    days,
    unassigned,
  };
}
