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
  const body = (await res.json().catch(() => null)) as ApiErrorResponse | null;
  return new ApiError(
    res.status,
    body?.code ?? "UNKNOWN",
    body?.message ?? "요청 처리 중 오류가 발생했어요.",
    body?.requestId ?? "",
    body?.fieldErrors,
  );
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

/** 인증 헤더 부착, {data: T} 언래핑, 실패 응답의 ApiError 변환을 공통으로 처리하는 fetch wrapper. */
export async function apiFetch<T>(
  path: string,
  accessToken?: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...options.headers,
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
    credentials: "include",
  });
  if (!res.ok) throw await parseApiError(res);
  const body = (await res.json()) as ApiResponse<T>;
  return body.data;
}
