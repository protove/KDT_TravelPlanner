"use client";

import { AuthLayout } from "@/components/templates/AuthLayout";
import { SocialLoginButton } from "@/components/molecules/SocialLoginButton";
import type { AuthProvider } from "@/lib/types/auth";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

const PROVIDER_LABEL: Record<AuthProvider, string> = {
  google: "구글",
  naver: "네이버",
};

export default function AuthPage() {
  // switchAccount 없이 호출하면 브라우저에 남아있는 SSO 세션으로 조용히 통과된다(평소 로그인).
  // "다른 계정으로 로그인"에서만 switchAccount=true를 붙여 프로바이더의 계정 선택 화면을 강제한다 —
  // 이 파라미터를 기본 로그인 버튼에도 무조건 붙였던 게 매번 계정 선택을 강제하던 버그였다.
  function handleLogin(provider: AuthProvider, options: { switchAccount?: boolean } = {}) {
    const qs = options.switchAccount ? "?switchAccount=true" : "";
    window.location.href = `${API_BASE_URL}/api/v1/auth/oauth2/${provider}${qs}`;
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

        <div className="mt-1 flex flex-col items-center gap-1">
          {(["google", "naver"] as const).map((provider) => (
            <button
              key={provider}
              type="button"
              onClick={() => handleLogin(provider, { switchAccount: true })}
              className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              {PROVIDER_LABEL[provider]} 다른 계정으로 로그인
            </button>
          ))}
        </div>
      </div>
    </AuthLayout>
  );
}
