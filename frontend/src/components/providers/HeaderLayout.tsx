"use client";

import * as React from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppHeader } from "@/components/organisms/AppHeader";
import { useAuthStore } from "@/lib/stores/useAuthStore";

// 로그인 전 화면(진입/콜백)은 자체 브랜딩만 보여주고 GNB가 필요 없다.
const HIDDEN_PATHS = ["/auth", "/auth/callback"];

export interface HeaderLayoutProps {
  children: React.ReactNode;
}

/**
 * 루트 레이아웃에 한 번만 마운트되는 공통 헤더.
 * 페이지별로 AppHeader를 각자 만들어 쓰면 라우트 이동마다 템플릿 트리가 통째로
 * 바뀌면서 헤더까지 언마운트→리마운트되어 새로고침처럼 깜빡였다 — 여기서 한 번만
 * 렌더링해 라우트가 바뀌어도 같은 인스턴스가 유지되게 한다.
 */
function HeaderLayout({ children }: HeaderLayoutProps) {
  const router = useRouter();
  const pathname = usePathname();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const user = useAuthStore((s) => s.user);

  const hideHeader = HIDDEN_PATHS.includes(pathname);

  return (
    <>
      {!hideHeader && (
        <AppHeader
          loggedIn={isLoggedIn}
          userInitial={user?.initial}
          nickname={user?.nickname}
          avatarColor={user?.avatarColor}
          avatarSrc={user?.profileImageUrl ?? undefined}
          onLogoClick={() => router.push(isLoggedIn ? "/trips" : "/")}
          onLoginClick={() => router.push("/auth")}
          onProfileClick={() => router.push("/mypage")}
          onNotificationClick={() => router.push("/notifications")}
        />
      )}
      {children}
    </>
  );
}

export { HeaderLayout };
