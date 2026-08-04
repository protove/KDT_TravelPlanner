import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // S3 + CloudFront 정적 호스팅 전환: 서버 없이 빌드 시점에 HTML을 전부 생성한다.
  // next/image의 서버 최적화도 서버가 없으면 못 쓰므로 unoptimized로 끈다(TripCard.tsx 영향).
  output: "export",
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default nextConfig;
