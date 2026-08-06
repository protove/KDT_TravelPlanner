"use client";

import { AuthLayout } from "@/components/templates/AuthLayout";
import { SocialLoginButton } from "@/components/molecules/SocialLoginButton";
import type { AuthProvider } from "@/lib/types/auth";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000";

export default function AuthPage() {
  function handleLogin(provider: AuthProvider) {
    window.location.href = `${API_BASE_URL}/api/v1/auth/oauth2/${provider}`;
  }

  return (
    <AuthLayout>
      <div className="mb-3.5 flex flex-col items-center gap-2.5 text-center">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-[15px] font-bold text-primary-foreground">
          T
        </div>
        <h1 className="text-2xl font-bold text-foreground">
          TripPlanner 시작하기
        </h1>
        <p className="text-sm text-muted-foreground">
          SSO 계정으로 로그인하면 자동으로 가입돼요
        </p>
      </div>

      <div className="flex flex-col gap-2.5">
        <SocialLoginButton
          provider="google"
          onClick={() => handleLogin("google")}
        />
        <SocialLoginButton
          provider="naver"
          onClick={() => handleLogin("naver")}
        />
        <p className="mt-1.5 text-center text-xs text-muted-foreground">
          가입 시 닉네임이 자동으로 생성돼요. 계속 진행하면 이용약관에 동의하는
          것으로 간주합니다.
        </p>
      </div>
    </AuthLayout>
  );
}
