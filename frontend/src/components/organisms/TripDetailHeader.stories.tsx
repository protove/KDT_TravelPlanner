import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripDetailHeader } from "./TripDetailHeader";
import type { Country, City } from "@/lib/api/location";
import type { TravelMember } from "@/lib/api/members";

const COUNTRIES: Country[] = [
  { countryId: 1, code: "JP", nameKo: "일본", nameEn: "Japan" },
  { countryId: 2, code: "KR", nameKo: "대한민국", nameEn: "Korea" },
];

const CITIES: City[] = [
  { cityId: 1, countryId: 1, nameKo: "도쿄", nameEn: "Tokyo", googlePlaceId: null, latitude: null, longitude: null },
  { cityId: 2, countryId: 1, nameKo: "오사카", nameEn: "Osaka", googlePlaceId: null, latitude: null, longitude: null },
];

const MEMBERS: TravelMember[] = [
  { userId: "u1", nickname: "규진", profileImageUrl: null, role: "OWNER", isOwner: true, status: "ACCEPTED", invitationId: null },
  { userId: "u2", nickname: "두루미", profileImageUrl: null, role: "READ_WRITE", isOwner: false, status: "ACCEPTED", invitationId: null },
];

const COMPANION_OPTIONS = ["혼자", "친구와", "가족과", "연인과"] as const;

/** 스토리에서 제목/기간/나라·도시/동행을 실제로 편집해볼 수 있도록 상태를 들고 있는 래퍼. */
function TripDetailHeaderDemo(props: { isOwner: boolean; canEdit: boolean }) {
  const [isEditing, setIsEditing] = React.useState(false);
  const [title, setTitle] = React.useState("도쿄 벚꽃 여행");
  const [titleDraft, setTitleDraft] = React.useState(title);
  const [countryId, setCountryId] = React.useState<number | null>(1);
  const [cityId, setCityId] = React.useState<number | null>(1);
  const [dateRange, setDateRange] = React.useState({ start: new Date(2027, 3, 2), end: new Date(2027, 3, 5) });
  const [showCalendar, setShowCalendar] = React.useState(false);
  const [companion, setCompanion] = React.useState<string>(COMPANION_OPTIONS[2]);

  return (
    <TripDetailHeader
      onBack={() => {}}
      title={title}
      isEditing={isEditing}
      titleDraft={titleDraft}
      onTitleDraftChange={setTitleDraft}
      canEdit={props.canEdit}
      onStartEdit={() => {
        setTitleDraft(title);
        setIsEditing(true);
      }}
      onSaveEdit={() => {
        setTitle(titleDraft.trim() || title);
        setIsEditing(false);
      }}
      onCancelEdit={() => setIsEditing(false)}
      isOwner={props.isOwner}
      onDeleteClick={() => {}}
      members={MEMBERS}
      onInviteClick={() => {}}
      onManageClick={() => {}}
      onLeaveClick={() => {}}
      countries={COUNTRIES}
      selectedCountryId={countryId}
      onCountryChange={(v) => {
        setCountryId(Number(v));
        setCityId(null);
      }}
      cities={CITIES.filter((c) => c.countryId === countryId)}
      selectedCityId={cityId}
      onCityChange={(v) => setCityId(Number(v))}
      selectedCountryName={COUNTRIES.find((c) => c.countryId === countryId)?.nameKo ?? "나라 미지정"}
      selectedCityName={CITIES.find((c) => c.cityId === cityId)?.nameKo ?? "도시 미지정"}
      dateRange={dateRange}
      onDateRangeChange={setDateRange}
      showCalendar={showCalendar}
      onToggleCalendar={() => setShowCalendar((v) => !v)}
      onApplyCalendar={() => setShowCalendar(false)}
      companion={companion}
      onCompanionChange={setCompanion}
      companionOptions={COMPANION_OPTIONS}
    />
  );
}

const meta = {
  title: "Organisms/TripDetailHeader",
  component: TripDetailHeaderDemo,
  tags: ["autodocs"],
  args: {
    isOwner: true,
    canEdit: true,
  },
} satisfies Meta<typeof TripDetailHeaderDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Owner: Story = {};

export const Member: Story = {
  args: { isOwner: false, canEdit: true },
};

export const ReadOnly: Story = {
  args: { isOwner: false, canEdit: false },
};
