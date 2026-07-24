"use client";

import * as React from "react";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { refreshAccessToken, fetchAuthUser } from "@/lib/api/auth";

/**
 * 앱이 처음 켜질 때(새로고침 포함) 딱 한 번, httpOnly refresh_token 쿠키로
 * 로그인 세션을 조용히 복구한다. accessToken은 zustand(메모리)에만 두고
 * localStorage 등에 영속화하지 않기 때문에, 새로고침으로 메모리가 날아갈 때마다
 * 이 과정을 거쳐야 로그인 상태가 유지된다.
 *
 * 성공/실패와 무관하게 마지막엔 반드시 isInitializing을 false로 내려서,
 * 페이지들의 로그인 가드가 "아직 확인 중"인 순간에 잘못 리다이렉트하지 않게 한다.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const setSession = useAuthStore((s) => s.setSession);
  const finishInitializing = useAuthStore((s) => s.finishInitializing);
  const hasRun = React.useRef(false);

  React.useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    (async () => {
      try {
        const accessToken = await refreshAccessToken();
        if (accessToken) {
          const user = await fetchAuthUser(accessToken);
          setSession(accessToken, user);
        }
      } catch (err) {
        console.error("세션 복구 실패:", err);
      } finally {
        finishInitializing();
      }
    })();
  }, [setSession, finishInitializing]);

  return <>{children}</>;
}
