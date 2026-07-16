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

function Demo() {
  const [activeTab, setActiveTab] = React.useState("profile");
  const [nickname, setNickname] = React.useState("김지민");
  const [gender, setGender] = React.useState<Gender>("unspecified");
  const [age, setAge] = React.useState<number | "">(28);

  return (
    <MyPageLayout header={<AppHeader loggedIn userInitial="지" />} tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab}>
      {activeTab === "profile" ? (
        <ProfileSection
          nickname={nickname}
          onNicknameChange={setNickname}
          gender={gender}
          onGenderChange={setGender}
          age={age}
          onAgeChange={(v) => setAge(v === "" ? "" : Number(v))}
          avatarColor="#3b82f6"
          onSave={() => {}}
        />
      ) : (
        <NotificationList
          notifications={[{ id: "1", inviterName: "박수아", tripTitle: "도쿄 벚꽃 여행" }]}
          onAccept={() => {}}
          onReject={() => {}}
        />
      )}
    </MyPageLayout>
  );
}

export const Default: Story = {
  args: { tabs, activeTab: "profile", onTabChange: () => {}, children: null },
  render: () => <Demo />,
};
