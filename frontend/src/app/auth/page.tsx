"use client";

import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { AuthLayout } from "@/components/templates/AuthLayout";
import { useAuthStore, type AuthProvider } from "@/lib/stores/useAuthStore";

export default function AuthPage() {
  const router = useRouter();
  const login = useAuthStore((s) => s.login);

  function handleLogin(provider: AuthProvider) {
    login(provider);
    router.push("/landing");
  }

  return (
    <AuthLayout>
      <div className="mb-3.5 flex flex-col items-center gap-2.5 text-center">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-[15px] font-bold text-primary-foreground">
          T
        </div>
        <h1 className="text-lg font-bold text-foreground">TripPlanner 시작하기</h1>
        <p className="text-xs text-muted-foreground">SSO 계정으로 로그인하면 자동으로 가입돼요</p>
      </div>

      <div className="flex flex-col gap-2.5">
        <Button variant="outline" className="w-full" onClick={() => handleLogin("google")}>
          구글로 계속하기
        </Button>
        <Button variant="outline" className="w-full" onClick={() => handleLogin("naver")}>
          네이버로 계속하기
        </Button>
        <p className="mt-1.5 text-center text-xs text-muted-foreground">
          가입 시 닉네임이 자동으로 생성돼요. 계속 진행하면 이용약관에 동의하는 것으로 간주합니다.
        </p>
      </div>
    </AuthLayout>
  );
}
