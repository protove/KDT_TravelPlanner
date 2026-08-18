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
            { id: "1", name: "나리타 국제공항", lat: 35.772, lng: 140.3929 },
            { id: "2", name: "신주쿠 숙소", lat: 35.6938, lng: 139.7034 },
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
        <TripDetailHeader
          onBack={() => {}}
          title="도쿄 벚꽃 여행"
          isEditing={false}
          titleDraft="도쿄 벚꽃 여행"
          onTitleDraftChange={() => {}}
          canEdit
          onStartEdit={() => {}}
          onSaveEdit={() => {}}
          onCancelEdit={() => {}}
          isOwner
          onDeleteClick={() => {}}
          members={[
            { userId: "u1", nickname: "규진", profileImageUrl: null, role: "OWNER", isOwner: true, status: "ACCEPTED", invitationId: null },
          ]}
          onInviteClick={() => {}}
          onManageClick={() => {}}
          onLeaveClick={() => {}}
          countries={[{ countryId: 1, code: "JP", nameKo: "일본", nameEn: "Japan" }]}
          selectedCountryId={1}
          onCountryChange={() => {}}
          cities={[{ cityId: 1, countryId: 1, nameKo: "도쿄", nameEn: "Tokyo", googlePlaceId: null, latitude: null, longitude: null }]}
          selectedCityId={1}
          onCityChange={() => {}}
          selectedCountryName="일본"
          selectedCityName="도쿄"
          dateRange={{ start: new Date(2027, 3, 2), end: new Date(2027, 3, 5) }}
          onDateRangeChange={() => {}}
          showCalendar={false}
          onToggleCalendar={() => {}}
          onApplyCalendar={() => {}}
          companion="친구와"
          onCompanionChange={() => {}}
          companionOptions={["혼자", "친구와", "가족과", "연인과"]}
        />
      }
      schedule={<ScheduleSlot />}
    />
  ),
};
