"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { AppHeader } from "@/components/organisms/AppHeader";
import { LandingLayout } from "@/components/templates/LandingLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";

export default function LandingPage() {
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
          onLogoClick={() => router.push("/landing")}
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
