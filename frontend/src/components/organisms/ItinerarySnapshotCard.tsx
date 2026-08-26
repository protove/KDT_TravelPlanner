"use client";

import * as React from "react";
import { Badge } from "@/components/atoms/Badge";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { MapPanel, type MapMarker } from "@/components/organisms/MapPanel";
import {
  ScheduleBoard,
  type ScheduleDayTab,
  type ScheduleEntry,
  type UnassignedPlace,
} from "@/components/organisms/ScheduleBoard";
import type { ItinerarySnapshot } from "@/lib/types/community";

export interface ItinerarySnapshotCardProps {
  snapshot: ItinerarySnapshot;
  className?: string;
}

function placeLabel(item: ItinerarySnapshot["days"][number]["items"][number]): string {
  return item.category === "음식" && item.foodSubcategory ? `${item.name} · ${item.foodSubcategory}` : item.name;
}

/**
 * 여행후기 게시글에 박제된 일정 스냅샷을 보여주는 읽기전용 카드.
 *
 * ScheduleBoard/MapPanel을 "그대로" 재사용한다 — 두 컴포넌트 파일 자체는 손대지 않는다(트립
 * 상세/지도 쪽을 다른 팀원이 따로 개선 중이라 그 파일들에 충돌을 내지 않기 위한 결정,
 * 2026-08-25 [[project_community_itinerary_snapshot]]). 그래서 알려진 사소한 흠이 하나 있다:
 * MapPanel의 "경로 최적화" 버튼은 readOnly 여부와 무관하게 항상 보이는데, onOptimizeRoute를
 * 안 넘기면 눌러도 아무 동작이 없다(죽은 버튼이지만 에러는 안 남). MapPanel을 고칠 수 있게 되면
 * 숨기는 prop을 추가하는 걸 고려할 것.
 */
function ItinerarySnapshotCard({ snapshot, className }: ItinerarySnapshotCardProps) {
  // 이 기능 초기 개발 중 스냅샷 데이터 스키마가 한 번 바뀌었다 — 그 이전에 만들어진 게시글은
  // itinerarySnapshotJson이 옛 모양(Tiptap 문서 등)으로 저장돼 있어 days가 없을 수 있다.
  // 그런 레거시/손상 데이터에서도 죽지 않고 "일정 없음"으로 보여주기 위한 방어 코드.
  const snapshotDays = Array.isArray(snapshot?.days) ? snapshot.days : [];

  const days: ScheduleDayTab[] = snapshotDays.map((day) => ({
    key: String(day.dayNumber),
    label: `${day.dayNumber}일차`,
  }));

  const [activeDay, setActiveDay] = React.useState(days[0]?.key ?? "1");
  const activeDayGroup = snapshotDays.find((day) => String(day.dayNumber) === activeDay) ?? snapshotDays[0];

  const items: ScheduleEntry[] = (activeDayGroup?.items ?? []).map((item) => ({
    id: item.timelineItemId,
    placeName: placeLabel(item),
  }));

  const markers: MapMarker[] = (activeDayGroup?.items ?? [])
    .filter((item) => item.lat != null && item.lng != null)
    .map((item) => ({ id: item.timelineItemId, name: item.name, lat: item.lat as number, lng: item.lng as number }));

  // 미배정(dayNumber 없음) 항목 — day가 없어 좌표가 없으므로 지도엔 안 찍히고 목록에만 나온다.
  const snapshotUnassigned = Array.isArray(snapshot?.unassigned) ? snapshot.unassigned : [];
  const unassigned: UnassignedPlace[] = snapshotUnassigned.map((item) => ({
    id: item.timelineItemId,
    name: placeLabel(item),
  }));

  const hasContent = days.length > 0 || unassigned.length > 0;

  return (
    <div className={className}>
      <div className="mb-3 flex items-center gap-2">
        <Badge variant="secondary">일정 스냅샷</Badge>
        <span className="text-xs text-fg-muted">작성 시점 일정이 고정되어 표시돼요.</span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-foreground">{snapshot.title}</span>
        <DateRangeBadge start={new Date(snapshot.startDate)} end={new Date(snapshot.endDate)} />
      </div>

      {hasContent ? (
        <ScheduleBoard
          days={days}
          activeDay={activeDay}
          onDayChange={setActiveDay}
          items={items}
          unassigned={unassigned}
          map={days.length > 0 ? <MapPanel markers={markers} /> : undefined}
          readOnly
        />
      ) : (
        <p className="text-sm text-muted-foreground">배정된 일정이 없어요.</p>
      )}
    </div>
  );
}

export { ItinerarySnapshotCard };
