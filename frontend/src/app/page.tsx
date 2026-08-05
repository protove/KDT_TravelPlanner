"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { AppHeader } from "@/components/organisms/AppHeader";
import { LandingLayout } from "@/components/templates/LandingLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";

export default function LandingPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const user = useAuthStore((s) => s.user);

  // 비로그인 랜딩은 로그인 상태에서는 의미가 없어 /trips로 보낸다 (IA: 로그인여부 X 전용 화면).
  // 세션 복구가 끝나기 전엔 isLoggedIn이 아직 기본값(false)이라, isInitializing이 끝날 때까지 판단을 미룬다.
  React.useEffect(() => {
    if (!isInitializing && isLoggedIn) router.replace("/trips");
  }, [isInitializing, isLoggedIn, router]);

  if (isInitializing || isLoggedIn) return null;

  return (
    <LandingLayout
      header={
        <AppHeader
          loggedIn={isLoggedIn}
          userInitial={user?.initial}
          avatarColor={user?.avatarColor}
          onLogoClick={() => router.push("/")}
          onLoginClick={() => router.push("/auth")}
        />
      }
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-base font-bold text-primary-foreground">
        T
      </div>
      <h1 className="max-w-md text-3xl font-bold leading-snug text-foreground">
        여행 일정을 함께 계획하세요
      </h1>
      <p className="max-w-sm text-[15px] text-fg-secondary">
        SSO 계정으로 간편하게 시작하고, 동행과 일정을 함께 만들어보세요.
      </p>
      <Button size="lg" onClick={() => router.push("/auth")}>
        시작하기
      </Button>
    </LandingLayout>
  );
}
