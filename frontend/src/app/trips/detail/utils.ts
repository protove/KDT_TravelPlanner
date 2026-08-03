import type { CompanionType, TimelineItem } from "@/lib/api/travel";

/** 날짜 탭 라벨에 쓰는 요일 표기. */
export const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export const COMPANION_OPTIONS = ["혼자", "연인과", "가족과", "친구와", "반려동물과", "기타"];

export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const COMPANION_LABELS: Record<CompanionType, string> = {
  SOLO: "혼자",
  COUPLE: "연인과",
  FAMILY: "가족과",
  FRIEND: "친구와",
  PET: "반려동물과",
  ETC: "기타",
};

export const COMPANION_TYPE_BY_LABEL: Record<string, CompanionType> = Object.fromEntries(
  Object.entries(COMPANION_LABELS).map(([type, label]) => [label, type as CompanionType]),
);

export function parseIsoDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatIsoDate(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/**
 * MapPanel은 아직 실제 지도 SDK 없이 x/y 퍼센트로만 마커를 찍는 mock 컴포넌트라
 * (실제 좌표 연동은 별도 프로젝트로 범위 밖), timelineItemId를 해시해 고정된
 * 위치를 만들어준다. 실제 지리적 위치를 의미하지 않는다.
 */
export function pseudoMapPosition(timelineItemId: string) {
  let hash = 0;
  for (let i = 0; i < timelineItemId.length; i++) hash = (hash * 31 + timelineItemId.charCodeAt(i)) >>> 0;
  return { x: 15 + (hash % 70), y: 15 + ((hash >>> 8) % 70) };
}

/** "정보 수정" 모드에서 아직 서버에 없는(로컬 draft) 일정 항목에 붙이는 임시 id 접두어. */
export const NEW_ITEM_PREFIX = "draft:";

export function computeNextVisitOrder(items: TimelineItem[], dayNumber: number | null): number {
  const sameDay = items.filter((t) => t.dayNumber === dayNumber);
  return sameDay.length === 0 ? 1 : Math.max(...sameDay.map((t) => t.visitOrder)) + 1;
}

/** visitDate(실제 날짜)를 기준으로, 주어진 시작일 하에서의 dayNumber(몇 번째 날)를 계산한다. */
export function dayNumberForStart(visitDateIso: string, start: Date): number {
  const visitDate = parseIsoDate(visitDateIso);
  const s = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const days = Math.round((visitDate.getTime() - s.getTime()) / (24 * 60 * 60 * 1000));
  return days + 1;
}

/**
 * 여행 기간(시작/종료일)이 바뀔 때, 이미 배정된 모든 항목을 "절대 날짜(visitDate) 고정" 기준으로
 * 다시 정리한다 — 새 기간 안에 있으면 dayNumber만 새 시작일 기준으로 재계산하고, 새 기간 밖으로
 * 벗어나면 미배정(삭제 아님)으로 되돌린다. 이번 편집 세션에서 직접 안 건드린 항목도 포함된다.
 */
export function reconcileForDateRange(items: TimelineItem[], newStart: Date, newEnd: Date): TimelineItem[] {
  const start = new Date(newStart.getFullYear(), newStart.getMonth(), newStart.getDate());
  const end = new Date(newEnd.getFullYear(), newEnd.getMonth(), newEnd.getDate());
  return items.map((item) => {
    if (item.dayNumber == null || !item.visitDate) return item;
    const visitDate = parseIsoDate(item.visitDate);
    if (visitDate.getTime() < start.getTime() || visitDate.getTime() > end.getTime()) {
      return { ...item, dayNumber: null, visitDate: null };
    }
    const newDayNumber = dayNumberForStart(item.visitDate, newStart);
    return newDayNumber !== item.dayNumber ? { ...item, dayNumber: newDayNumber } : item;
  });
}

/**
 * UI에서 미리 계산해둔 visitOrder는 이후 편집(날짜 재배정, 다른 항목 추가/삭제 등)을 거치며
 * 서로 어긋날 수 있다. 저장 직전에 날짜별로 기존 순서를 유지한 채 1,2,3...으로 다시 번호를
 * 매겨서, 같은 날짜에 순서가 중복되는 일이 없도록 확정한다.
 */
export function normalizeVisitOrders(items: TimelineItem[]): TimelineItem[] {
  const groups = new Map<number, TimelineItem[]>();
  for (const item of items) {
    if (item.dayNumber == null) continue;
    const group = groups.get(item.dayNumber) ?? [];
    group.push(item);
    groups.set(item.dayNumber, group);
  }
  const orderByItem = new Map<TimelineItem, number>();
  for (const group of groups.values()) {
    const sorted = [...group].sort((a, b) => a.visitOrder - b.visitOrder);
    sorted.forEach((item, i) => orderByItem.set(item, i + 1));
  }
  return items.map((item) => {
    const newOrder = orderByItem.get(item);
    return newOrder != null && newOrder !== item.visitOrder ? { ...item, visitOrder: newOrder } : item;
  });
}

export function getDateTabs(start: Date, end: Date) {
  const tabs: { key: string; label: string; date: Date }[] = [];
  const cur = new Date(start);
  while (cur <= end) {
    tabs.push({
      key: String(tabs.length),
      label: `${cur.getMonth() + 1}/${cur.getDate()} (${WEEKDAYS[cur.getDay()]})`,
      date: new Date(cur),
    });
    cur.setDate(cur.getDate() + 1);
  }
  return tabs;
}
