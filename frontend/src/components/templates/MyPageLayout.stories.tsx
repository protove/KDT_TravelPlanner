import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppHeader } from "@/components/organisms/AppHeader";
import { ProfileSection, type Gender } from "@/components/organisms/ProfileSection";
import { NotificationList } from "@/components/organisms/NotificationList";
import { MyPageLayout } from "./MyPageLayout";

const meta = {
  title: "Templates/MyPageLayout",
  component: MyPageLayout,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof MyPageLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

const tabs = [
  { key: "profile", label: "프로필 수정" },
  { key: "invites", label: "초대 알림" },
];

const manyTabs = [
  { key: "profile", label: "프로필 수정" },
  { key: "invites", label: "초대 알림" },
  { key: "companions", label: "같이 여행간 사용자" },
  { key: "settings", label: "설정" },
];

function Demo({ tabList = tabs }: { tabList?: typeof tabs }) {
  const [activeTab, setActiveTab] = React.useState(tabList[0].key);
  const [nickname, setNickname] = React.useState("김지민");
  const [gender, setGender] = React.useState<Gender>("female");
  const [age, setAge] = React.useState<number | "">(28);

  return (
    <MyPageLayout header={<AppHeader loggedIn userInitial="지" />} tabs={tabList} activeTab={activeTab} onTabChange={setActiveTab}>
      {activeTab === "profile" ? (
        <ProfileSection
          nickname={nickname}
          onNicknameChange={setNickname}
          gender={gender}
          onGenderChange={setGender}
          age={age}
          onAgeChange={(v) => setAge(v === "" ? "" : Number(v))}
          avatarColor="var(--brand-600)"
          onSave={() => {}}
        />
      ) : activeTab === "invites" ? (
        <NotificationList
          notifications={[{ id: "1", inviterName: "박수아", tripTitle: "도쿄 벚꽃 여행" }]}
          onAccept={() => {}}
          onReject={() => {}}
        />
      ) : null}
    </MyPageLayout>
  );
}

export const Default: Story = {
  args: { tabs, activeTab: "profile", onTabChange: () => {}, children: null },
  render: () => <Demo />,
};

// md(768px) 미만 폭 데모 — 탭 2개는 다 들어가서 스크롤 힌트가 안 보이는 게 정상 (front.md §6)
export const MobileWidth: Story = {
  args: { tabs, activeTab: "profile", onTabChange: () => {}, children: null },
  render: () => (
    <div style={{ width: 360, border: "1px solid var(--border)", margin: "0 auto" }}>
      <Demo />
    </div>
  ),
};

// md 미만 + 탭 4개 — 가로 스크롤 탭바가 넘쳐서 오른쪽 페이드+화살표 힌트가 보여야 정상 (front.md §6)
export const MobileWidthOverflowingTabs: Story = {
  args: { tabs: manyTabs, activeTab: "profile", onTabChange: () => {}, children: null },
  render: () => (
    <div style={{ width: 360, border: "1px solid var(--border)", margin: "0 auto" }}>
      <Demo tabList={manyTabs} />
    </div>
  ),
};
