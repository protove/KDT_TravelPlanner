import { NextResponse } from "next/server";

/**
 * 예전엔 여기서 `logged_in` 쿠키(클라이언트가 직접 세팅, 최대 7일)를 보고
 * /trips 등 보호 라우트를 엣지에서 막았다. 근데 이 쿠키는 실제 서버 세션(리프레시 토큰)
 * 상태와 어긋날 수 있어서 — 서버가 재시작돼 세션이 죽어도 쿠키는 그대로 남아있는 식 —
 * 로그인 화면 자체에 도달을 못 하는 리다이렉트 루프가 생겼었다.
 *
 * 각 페이지(trips/page.tsx, landing/page.tsx 등)는 이미 useAuthStore의 실제
 * isLoggedIn 값(세션 복구 결과)으로 자체적으로 리다이렉트하고 있으므로,
 * 여기서는 권한 검사를 하지 않고 그대로 통과시킨다.
 */
export function middleware() {
  return NextResponse.next();
}
