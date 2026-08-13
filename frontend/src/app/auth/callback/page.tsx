"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { exchangeCodeForToken, fetchAuthUser } from "@/lib/api/auth";

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);
  const code = searchParams.get("code");
  const oauthError = searchParams.get("error");
  const [error, setError] = useState<string | null>(
    code
      ? null
      : oauthError === "withdrawn_account"
        ? "이미 탈퇴한 계정이에요. 같은 소셜 계정으로는 다시 가입할 수 없어요."
        : "로그인 코드가 없어요. 다시 로그인해주세요.",
  );
  const hasRun = useRef(false);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    if (!code) return;

    (async () => {
      try {
        const accessToken = await exchangeCodeForToken(code);
        const user = await fetchAuthUser(accessToken);
        setSession(accessToken, user);
        router.replace("/trips");
      } catch {
        setError("로그인 처리 중 문제가 생겼어요. 다시 시도해주세요.");
      }
    })();
  }, [code, setSession, router]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <button
          type="button"
          className="cursor-pointer text-sm text-muted-foreground underline"
          onClick={() => router.replace("/auth")}
        >
          다시 로그인하기
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-muted-foreground">로그인 처리 중...</p>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <p className="text-sm text-muted-foreground">로그인 처리 중...</p>
        </div>
      }
    >
      <AuthCallbackContent />
    </Suspense>
  );
}
