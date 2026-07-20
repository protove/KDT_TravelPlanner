"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { AppHeader } from "@/components/organisms/AppHeader";
import { LandingLayout } from "@/components/templates/LandingLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";

export default function ForbiddenPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const user = useAuthStore((s) => s.user);

  return (
    <LandingLayout
      header={
        <AppHeader
          loggedIn={isLoggedIn}
          userInitial={user?.initial}
          avatarColor={user?.avatarColor}
          onLogoClick={() => router.push(isLoggedIn ? "/trips" : "/landing")}
          onLoginClick={() => router.push("/auth")}
        />
      }
    >
      <div className="text-5xl font-bold text-border-strong">403</div>
      <h1 className="text-lg font-bold text-foreground">접근 권한이 없어요</h1>
      <p className="max-w-xs text-sm text-muted-foreground">초대받지 않았거나 삭제된 일정입니다.</p>
      <Button onClick={() => router.push("/trips")}>목록으로 돌아가기</Button>
    </LandingLayout>
  );
}
