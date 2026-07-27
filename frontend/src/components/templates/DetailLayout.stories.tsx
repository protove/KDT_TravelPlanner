import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppHeader } from "@/components/organisms/AppHeader";
import { TripDetailHeader } from "@/components/organisms/TripDetailHeader";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import { MapPanel } from "@/components/organisms/MapPanel";
import { DetailLayout } from "./DetailLayout";

const meta = {
  title: "Templates/DetailLayout",
  component: DetailLayout,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof DetailLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

function ScheduleSlot() {
  const [activeDay, setActiveDay] = React.useState("d1");
  return (
    <ScheduleBoard
      days={[
        { key: "d1", label: "4/2 (금)" },
        { key: "d2", label: "4/3 (토)" },
      ]}
      activeDay={activeDay}
      onDayChange={setActiveDay}
      items={[{ id: "1", placeName: "나리타 국제공항", note: "도착 후 리무진버스로 이동" }]}
      unassigned={[{ id: "u1", name: "시부야 스카이" }]}
      map={
        <MapPanel
          markers={[
            { id: "1", name: "나리타 국제공항", x: 20, y: 30 },
            { id: "2", name: "신주쿠 숙소", x: 55, y: 45 },
          ]}
        />
      }
    />
  );
}

export const Default: Story = {
  args: { schedule: null },
  render: () => (
    <DetailLayout
      header={<AppHeader loggedIn userInitial="지" />}
      detailHeader={
        <TripDetailHeader title="도쿄 벚꽃 여행" start={new Date(2027, 3, 2)} end={new Date(2027, 3, 5)} />
      }
      schedule={<ScheduleSlot />}
    />
  ),
};
