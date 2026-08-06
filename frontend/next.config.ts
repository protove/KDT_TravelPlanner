import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // S3 + CloudFront 정적 호스팅 전환: 서버 없이 빌드 시점에 HTML을 전부 생성한다.
  // next/image의 서버 최적화도 서버가 없으면 못 쓰므로 unoptimized로 끈다(TripCard.tsx 영향).
  output: "export",
  // CloudFront Function이 "/path/"를 "/path/index.html"로 rewrite하므로
  // export 산출물도 동일한 디렉터리+index.html 구조로 맞춘다(안 그러면 /auth/callback/에서 S3 AccessDenied).
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;
