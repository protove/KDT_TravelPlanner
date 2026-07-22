"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore, type Gender } from "@/lib/stores/useAuthStore";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

interface AccessTokenResponse {
  data: {
    accessToken: string;
    tokenType: string;
    expiresAt: string;
  };
}

interface UserProfileResponse {
  data: {
    provider: "GOOGLE" | "NAVER";
    name: string | null;
    nickname: string | null;
    gender: "MALE" | "FEMALE" | "OTHER" | "UNSPECIFIED" | null;
    birthYear: number | null;
  };
}

function mapGender(gender: UserProfileResponse["data"]["gender"]): Gender {
  if (gender === "MALE") return "male";
  if (gender === "FEMALE") return "female";
  return "unspecified";
}

function AuthCallbackContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);
  const [error, setError] = useState<string | null>(null);
  const hasRun = useRef(false);

  useEffect(() => {
    if (hasRun.current) return;
    hasRun.current = true;

    const code = searchParams.get("code");
    if (!code) {
      setError("로그인 코드가 없어요. 다시 로그인해주세요.");
      return;
    }

    (async () => {
      try {
        const exchangeRes = await fetch(`${API_BASE_URL}/api/v1/auth/token/exchange`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ code }),
        });
        if (!exchangeRes.ok) throw new Error("토큰 교환 실패");
        const exchangeBody = (await exchangeRes.json()) as AccessTokenResponse;
        const accessToken = exchangeBody.data.accessToken;

        const profileRes = await fetch(`${API_BASE_URL}/api/v1/users/me/profile`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          credentials: "include",
        });
        if (!profileRes.ok) throw new Error("프로필 조회 실패");
        const profileBody = (await profileRes.json()) as UserProfileResponse;
        const profile = profileBody.data;

        const nickname = profile.nickname ?? profile.name ?? "여행자";
        setSession(accessToken, {
          nickname,
          initial: nickname.slice(0, 1) || "여",
          avatarColor: profile.provider === "GOOGLE" ? "#3b82f6" : "#03c75a",
          gender: mapGender(profile.gender),
          age: profile.birthYear ? new Date().getFullYear() - profile.birthYear + 1 : "",
        });

        router.replace("/trips");
      } catch (err) {
        console.error(err);
        setError("로그인 처리 중 문제가 생겼어요. 다시 시도해주세요.");
      }
    })();
  }, [searchParams, setSession, router]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <button
          type="button"
          className="text-sm text-muted-foreground underline"
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
