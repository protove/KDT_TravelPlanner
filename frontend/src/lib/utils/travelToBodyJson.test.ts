import assert from "node:assert/strict";
import { test } from "node:test";

import type { TravelDetail } from "@/lib/api/travel";
import type { TiptapDocument } from "@/lib/types/community";

import { travelToBodyJson } from "./travelToBodyJson";

const sampleTravel: TravelDetail = {
  travelId: "travel-1",
  ownerId: "user-1",
  title: "도쿄 여행",
  startDate: "2026-03-01",
  endDate: "2026-03-02",
  travelDays: 2,
  countryId: 1,
  cityId: 1,
  companionType: "FRIEND",
  participantCount: 2,
  comment: null,
  version: 1,
  permission: "OWNER",
  timelineItems: [
    {
      timelineItemId: "item-2",
      dayNumber: 1,
      visitDate: "2026-03-01",
      cityId: 1,
      category: "관광지",
      foodSubcategory: null,
      name: "센소지",
      googlePlaceId: null,
      visitOrder: 2,
      memo: null,
    },
    {
      timelineItemId: "item-1",
      dayNumber: 1,
      visitDate: "2026-03-01",
      cityId: 1,
      category: "음식",
      foodSubcategory: "라멘",
      name: "이치란",
      googlePlaceId: null,
      visitOrder: 1,
      memo: null,
    },
    {
      timelineItemId: "item-3",
      dayNumber: 2,
      visitDate: "2026-03-02",
      cityId: 1,
      category: "관광지",
      foodSubcategory: null,
      name: "시부야",
      googlePlaceId: null,
      visitOrder: 1,
      memo: null,
    },
    {
      timelineItemId: "item-unassigned",
      dayNumber: null,
      visitDate: null,
      cityId: 1,
      category: "기타",
      foodSubcategory: null,
      name: "미배정 항목",
      googlePlaceId: null,
      visitOrder: 1,
      memo: null,
    },
  ],
};

test("travelToBodyJson: 제목 heading, 빈 문단, 일차별 heading+bulletList를 순서대로 생성한다", () => {
  const expected: TiptapDocument = {
    type: "doc",
    content: [
      {
        type: "heading",
        attrs: { level: 2 },
        content: [{ type: "text", text: "도쿄 여행 (2026-03-01~2026-03-02)" }],
      },
      { type: "paragraph" },
      {
        type: "heading",
        attrs: { level: 3 },
        content: [{ type: "text", text: "1일차 — 2026-03-01" }],
      },
      {
        type: "bulletList",
        content: [
          {
            type: "listItem",
            content: [{ type: "paragraph", content: [{ type: "text", text: "이치란 · 라멘" }] }],
          },
          {
            type: "listItem",
            content: [{ type: "paragraph", content: [{ type: "text", text: "센소지" }] }],
          },
        ],
      },
      {
        type: "heading",
        attrs: { level: 3 },
        content: [{ type: "text", text: "2일차 — 2026-03-02" }],
      },
      {
        type: "bulletList",
        content: [
          {
            type: "listItem",
            content: [{ type: "paragraph", content: [{ type: "text", text: "시부야" }] }],
          },
        ],
      },
    ],
  };

  assert.deepStrictEqual(travelToBodyJson(sampleTravel), expected);
});
