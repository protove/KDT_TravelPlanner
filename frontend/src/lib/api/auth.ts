import type { AuthUser, Gender } from "@/lib/stores/useAuthStore";

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

function mapProfile(profile: UserProfileResponse["data"]): AuthUser {
  const nickname = profile.nickname ?? profile.name ?? "여행자";
  return {
    nickname,
    initial: nickname.slice(0, 1) || "여",
    avatarColor: profile.provider === "GOOGLE" ? "#3b82f6" : "#03c75a",
    gender: mapGender(profile.gender),
    age: profile.birthYear ? new Date().getFullYear() - profile.birthYear + 1 : "",
  };
}

/** OAuth 콜백에서 받은 1회용 exchange code를 진짜 access token으로 교환한다. */
export async function exchangeCodeForToken(code: string): Promise<string> {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/token/exchange`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error("토큰 교환에 실패했어요.");
  const body = (await res.json()) as AccessTokenResponse;
  return body.data.accessToken;
}

/**
 * httpOnly refresh_token 쿠키로 새 access token을 조용히 재발급받는다.
 * 쿠키가 없거나 만료됐으면 null을 반환한다 (에러를 던지지 않음 — 비로그인 상태는 정상 케이스).
 */
export async function refreshAccessToken(): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/auth/token/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return null;
    const body = (await res.json()) as AccessTokenResponse;
    return body.data.accessToken;
  } catch {
    return null;
  }
}

/** access token으로 로그인한 유저의 프로필을 조회해 AuthUser 형태로 변환한다. */
export async function fetchAuthUser(accessToken: string): Promise<AuthUser> {
  const res = await fetch(`${API_BASE_URL}/api/v1/users/me/profile`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: "include",
  });
  if (!res.ok) throw new Error("프로필 조회에 실패했어요.");
  const body = (await res.json()) as UserProfileResponse;
  return mapProfile(body.data);
}

/** 서버의 refresh token을 폐기한다. 실패해도 클라이언트 로그아웃은 계속 진행되도록 에러를 삼킨다. */
export async function requestLogout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // 서버 로그아웃 실패해도 클라이언트 상태는 초기화해야 하므로 무시한다.
  }
}
