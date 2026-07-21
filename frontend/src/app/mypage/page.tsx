"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { AppHeader } from "@/components/organisms/AppHeader";
import { ProfileSection } from "@/components/organisms/ProfileSection";
import { NotificationList } from "@/components/organisms/NotificationList";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { MyPageLayout } from "@/components/templates/MyPageLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useNotificationStore } from "@/lib/stores/useNotificationStore";

type MypageTab = "profile" | "notif";

const TABS = [
  { key: "profile", label: "프로필수정" },
  { key: "notif", label: "초대알림" },
];

export default function MypagePage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);
  const logout = useAuthStore((s) => s.logout);
  const notifications = useNotificationStore((s) => s.notifications);
  const acceptNotification = useNotificationStore((s) => s.accept);
  const rejectNotification = useNotificationStore((s) => s.reject);

  const [tab, setTab] = React.useState<MypageTab>("profile");
  const [showWithdraw, setShowWithdraw] = React.useState(false);

  React.useEffect(() => {
    if (!isLoggedIn) router.replace("/landing");
  }, [isLoggedIn, router]);

  if (!isLoggedIn || !user) return null;

  function handleLogout() {
    logout();
    router.push("/landing");
  }

  function handleWithdraw() {
    logout();
    router.push("/landing");
  }

  return (
    <MyPageLayout
      header={<AppHeader loggedIn userInitial={user.initial} avatarColor={user.avatarColor} onLogoClick={() => router.push("/trips")} onProfileClick={() => router.push("/mypage")} onNotificationClick={() => router.push("/notifications")} />}
      tabs={TABS}
      activeTab={tab}
      onTabChange={(key) => setTab(key as MypageTab)}
    >
      {tab === "profile" ? (
        <>
          <h1 className="mb-5 text-xl font-bold text-foreground">프로필수정</h1>
          <ProfileSection
            nickname={user.nickname}
            onNicknameChange={(nickname) => updateProfile({ nickname })}
            gender={user.gender}
            onGenderChange={(gender) => updateProfile({ gender })}
            age={user.age}
            onAgeChange={(value) => updateProfile({ age: value === "" ? "" : Number(value) })}
            avatarColor={user.avatarColor}
            onSave={() => {}}
            className="mb-5 rounded-xl bg-card p-5 shadow-card"
          />
          <Button variant="outline" className="mb-2 w-full" onClick={handleLogout}>
            로그아웃
          </Button>
          <Button variant="outline" className="w-full text-destructive" onClick={() => setShowWithdraw(true)}>
            회원 탈퇴
          </Button>

          <ConfirmDialog
            open={showWithdraw}
            onOpenChange={setShowWithdraw}
            title="정말 탈퇴하시겠어요?"
            description="계정과 생성한 여행일정이 모두 삭제되며 되돌릴 수 없습니다."
            confirmLabel="탈퇴하기"
            destructive
            onConfirm={handleWithdraw}
          />
        </>
      ) : (
        <>
          <h1 className="mb-5 text-xl font-bold text-foreground">초대알림</h1>
          <NotificationList
            notifications={notifications}
            onAccept={acceptNotification}
            onReject={rejectNotification}
          />
        </>
      )}
    </MyPageLayout>
  );
}
