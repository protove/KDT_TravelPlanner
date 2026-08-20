import type { TimelineItem, TravelDetail } from "@/lib/api/travel";
import type {
  TiptapBlockNode,
  TiptapBulletListNode,
  TiptapDocument,
  TiptapHeadingNode,
  TiptapListItemNode,
  TiptapParagraphNode,
} from "@/lib/types/community";

function headingNode(level: 2 | 3, text: string): TiptapHeadingNode {
  return { type: "heading", attrs: { level }, content: [{ type: "text", text }] };
}

function textParagraphNode(text: string): TiptapParagraphNode {
  return { type: "paragraph", content: [{ type: "text", text }] };
}

function timelineItemListItem(item: TimelineItem): TiptapListItemNode {
  const text =
    item.category === "음식" && item.foodSubcategory
      ? `${item.name} · ${item.foodSubcategory}`
      : item.name;
  return { type: "listItem", content: [textParagraphNode(text)] };
}

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
 * 여행 상세(TravelDetail)를 커뮤니티 게시글 bodyJson(TiptapDocument)으로 변환한다.
 * docs/community-api-contract.md 6-4절 규칙: 제목 heading -> 빈 문단 -> dayNumber별
 * (heading + bulletList) 반복. dayNumber가 없는(미배정) 항목은 변환 대상에서 제외한다.
 */
export function travelToBodyJson(travel: TravelDetail): TiptapDocument {
  const itemsByDay = groupByDayNumber(travel.timelineItems);
  const dayGroups = Array.from(itemsByDay.entries()).sort(([a], [b]) => a - b);

  const content: TiptapBlockNode[] = [
    headingNode(2, `${travel.title} (${travel.startDate}~${travel.endDate})`),
    { type: "paragraph" },
  ];

  for (const [dayNumber, items] of dayGroups) {
    const dayItems = [...items].sort((a, b) => a.visitOrder - b.visitOrder);
    const visitDate = dayItems.find((item) => item.visitDate != null)?.visitDate ?? "";

    content.push(headingNode(3, `${dayNumber}일차 — ${visitDate}`));

    const bulletList: TiptapBulletListNode = {
      type: "bulletList",
      content: dayItems.map(timelineItemListItem),
    };
    content.push(bulletList);
  }

  return { type: "doc", content };
}
