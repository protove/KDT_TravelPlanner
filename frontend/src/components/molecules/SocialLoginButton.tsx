import * as React from "react";
import { cn } from "@/lib/utils";
import type { AuthProvider } from "@/lib/types/auth";

const PROVIDER_ASSET: Record<AuthProvider, { src: string; alt: string }> = {
  google: { src: "/icons/google-signin-light.svg", alt: "Google로 로그인" },
  naver: { src: "/icons/naver-login-light-narrow.png", alt: "네이버로 로그인" },
};

export interface SocialLoginButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  provider: AuthProvider;
}

/**
 * 각 사가 배포한 공식 로그인 버튼 에셋(frontend/public/icons)을 그대로 사용한다.
 * 브랜드 가이드라인상 색상/로고/텍스트를 임의로 변형하지 않는다.
 */
const SocialLoginButton = React.forwardRef<HTMLButtonElement, SocialLoginButtonProps>(
  ({ provider, className, ...props }, ref) => {
    const asset = PROVIDER_ASSET[provider];
    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          "flex w-full cursor-pointer items-center justify-center rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- 고정 에셋을 원본 비율 그대로 표시 */}
        <img src={asset.src} alt={asset.alt} className="w-full" />
      </button>
    );
  }
);
SocialLoginButton.displayName = "SocialLoginButton";

export { SocialLoginButton };
