import { refreshAccessToken } from "@/lib/api/auth";
import { useAuthStore } from "@/lib/stores/useAuthStore";

/** 백엔드 ApiResponse<T>(global/response/ApiResponse.kt)와 대응하는 성공 응답 껍데기. */
export interface ApiResponse<T> {
  data: T;
}

/** 백엔드 ApiErrorResponse(global/exception/ApiErrorResponse.kt)와 대응하는 실패 응답 껍데기. */
export interface ApiErrorResponse {
  code: string;
  message: string;
  requestId: string;
  fieldErrors?: { field: string; reason: string }[];
}

/** 실패 응답을 던질 때 쓰는 에러. status로 401/403/404 등을 구분해서 처리할 수 있다. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId: string,
    public fieldErrors?: { field: string; reason: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseApiError(res: Response): Promise<ApiError> {
  const body = (await res
    .json()
    .catch(() => null)) as ApiErrorResponse | null;

  return new ApiError(
    res.status,
    body?.code ?? "UNKNOWN",
    body?.message ?? "요청 처리 중 오류가 발생했어요.",
    body?.requestId ?? "",
    body?.fieldErrors,
  );
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8080";

// access token TTL(기본 30분)이 지나면 화면은 로그인 상태(isLoggedIn: true)로 남아 있는데
// 실제 API 호출은 계속 401을 받는 문제가 있었다 — AuthProvider의 silent refresh는 앱 부팅
// 시 딱 한 번만 돌기 때문. apiFetch가 401을 만나면 여기서 재발급을 시도하고, 성공하면 원요청을
// 새 토큰으로 1회 재시도한다. refreshAccessToken 자체가 dedup되어 있어(auth.ts 참고) 다른
// 호출자(AuthProvider 등)와 동시에 401을 맞아도 실제 재발급 요청은 하나만 나간다.
async function fetchWithReauth(
  path: string,
  accessToken: string | null | undefined,
  options: RequestInit,
  isRetry: boolean,
): Promise<Response> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...options.headers,
      ...(accessToken
        ? {
            Authorization: `Bearer ${accessToken}`,
          }
        : {}),
    },
    credentials: "include",
  });

  if (res.status !== 401 || isRetry) return res;

  const refreshedToken = await refreshAccessToken();
  if (!refreshedToken) {
    // 재발급도 실패했으면 refresh_token 쿠키 자체가 없거나 만료된 것 — 로그인 상태를
    // 정리해서 화면(isLoggedIn)과 실제 인증 상태가 다시 어긋나지 않게 한다. 각 페이지의
    // 기존 "!isLoggedIn이면 리다이렉트" 가드가 이 상태 변화를 그대로 이어받는다.
    useAuthStore.getState().logout();
    return res;
  }

  useAuthStore.getState().setAccessToken(refreshedToken);
  return fetchWithReauth(path, refreshedToken, options, true);
}

/** 인증 헤더 부착, {data: T} 언래핑, 실패 응답의 ApiError 변환을 공통으로 처리하는 fetch wrapper. */
export async function apiFetch<T>(
  path: string,
  accessToken?: string | null,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetchWithReauth(path, accessToken, options, false);
  if (!res.ok) throw await parseApiError(res);
  const body = (await res.json()) as ApiResponse<T>;

  return body.data;
}