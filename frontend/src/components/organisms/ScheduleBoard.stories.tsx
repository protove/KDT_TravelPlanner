import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { ScheduleBoard } from "./ScheduleBoard";
import { MapPanel } from "./MapPanel";

const meta = {
  title: "Organisms/ScheduleBoard",
  component: ScheduleBoard,
  tags: ["autodocs"],
} satisfies Meta<typeof ScheduleBoard>;

export default meta;
type Story = StoryObj<typeof meta>;

const days = [
  { key: "d1", label: "4/2 (금)" },
  { key: "d2", label: "4/3 (토)" },
  { key: "d3", label: "4/4 (일)" },
];

const itemsByDay: Record<string, { id: string; placeName: string; note?: string }[]> = {
  d1: [
    { id: "1", placeName: "나리타 국제공항", note: "도착 후 리무진버스로 이동" },
    { id: "2", placeName: "신주쿠 숙소 체크인" },
  ],
  d2: [{ id: "3", placeName: "메이지 신궁", note: "오전 산책" }],
  d3: [],
};

function Demo() {
  const [activeDay, setActiveDay] = React.useState("d1");
  return (
    <ScheduleBoard
      days={days}
      activeDay={activeDay}
      onDayChange={setActiveDay}
      items={itemsByDay[activeDay]}
      unassigned={[
        { id: "u1", name: "시부야 스카이" },
        { id: "u2", name: "츠키지 시장" },
      ]}
    />
  );
}

export const Default: Story = {
  args: { days, activeDay: "d1", onDayChange: () => {}, items: itemsByDay.d1 },
  render: () => <Demo />,
};

function DemoWithMap() {
  const [activeDay, setActiveDay] = React.useState("d1");
  return (
    <ScheduleBoard
      days={days}
      activeDay={activeDay}
      onDayChange={setActiveDay}
      items={itemsByDay[activeDay]}
      unassigned={[{ id: "u1", name: "시부야 스카이" }]}
      map={
        <MapPanel
          markers={[
            { id: "1", name: "나리타 국제공항", lat: 35.772, lng: 140.3929 },
            { id: "2", name: "신주쿠 숙소", lat: 35.6938, lng: 139.7034 },
          ]}
        />
      }
    />
  );
}

/** 초안 순서(탭 → 지도 → 일정 목록)대로 map 슬롯을 채운 형태. */
export const WithMap: Story = {
  args: { days, activeDay: "d1", onDayChange: () => {}, items: itemsByDay.d1 },
  render: () => <DemoWithMap />,
};

function DemoReorderable() {
  const [activeDay, setActiveDay] = React.useState("d1");
  const [itemsState, setItemsState] = React.useState(itemsByDay);

  function handleReorderItems(orderedIds: string[]) {
    setItemsState((prev) => {
      const byId = new Map(prev[activeDay].map((item) => [item.id, item]));
      return { ...prev, [activeDay]: orderedIds.map((id) => byId.get(id)!) };
    });
  }

  return (
    <ScheduleBoard
      days={days}
      activeDay={activeDay}
      onDayChange={setActiveDay}
      items={itemsState[activeDay]}
      onReorderItems={handleReorderItems}
    />
  );
}

/** 드래그 손잡이(⠿)를 눌러 카드 순서를 바꿀 수 있다. readOnly가 아닐 때만 손잡이가 보인다. */
export const Reorderable: Story = {
  args: { days, activeDay: "d1", onDayChange: () => {}, items: itemsByDay.d1 },
  render: () => <DemoReorderable />,
};

function DemoReadOnly() {
  const [activeDay, setActiveDay] = React.useState("d1");
  return (
    <ScheduleBoard
      days={days}
      activeDay={activeDay}
      onDayChange={setActiveDay}
      items={itemsByDay[activeDay]}
      unassigned={[{ id: "u1", name: "시부야 스카이" }]}
      readOnly
    />
  );
}

/** READ_ONLY 권한으로 조회할 때: 수정/취소/삭제 버튼이 전부 숨겨진다. */
export const ReadOnly: Story = {
  args: { days, activeDay: "d1", onDayChange: () => {}, items: itemsByDay.d1, readOnly: true },
  render: () => <DemoReadOnly />,
};
