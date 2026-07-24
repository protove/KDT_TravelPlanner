"use client";

import { useRouter } from "next/navigation";
import { AppHeader } from "@/components/organisms/AppHeader";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";

export default function CommunityPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);

  return (
    <ListLayout
      header={
        <AppHeader
          loggedIn
          userInitial={user?.initial}
          avatarColor={user?.avatarColor}
          onLogoClick={() => router.push("/trips")}
          onProfileClick={() => router.push("/mypage")}
          onNotificationClick={() => router.push("/notifications")}
        />
      }
      title={<h1 className="text-2xl font-bold text-foreground">커뮤니티</h1>}
    >
      <p className="text-sm text-muted-foreground">
        공개된 여행 일정을 둘러보는 화면입니다.
      </p>
    </ListLayout>
  );
}
