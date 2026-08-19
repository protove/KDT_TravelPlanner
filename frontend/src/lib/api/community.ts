import { apiFetch } from "@/lib/api/client";
import type {
  CommunityCategory,
  CommunityPostCreateRequest,
  CommunityPostDetail,
  CommunityPostSummary,
} from "@/lib/types/community";

export interface PageResponse<T> {
  content: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
  isFirst: boolean;
  isLast: boolean;
}

/** 카테고리 목록(탭용)을 조회한다. */
export async function getCategories(accessToken: string): Promise<CommunityCategory[]> {
  return apiFetch<CommunityCategory[]>("/api/v1/community/categories", accessToken);
}

export interface CommunityPostCreateResponse {
  postId: string;
}

/** 게시글을 작성한다. sourceTravelId 포함 시 서버가 해당 travel 조회 권한을 재검증한다. */
export async function createPost(
  accessToken: string,
  request: CommunityPostCreateRequest,
): Promise<CommunityPostCreateResponse> {
  return apiFetch<CommunityPostCreateResponse>("/api/v1/community/posts", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** 게시글 상세를 조회한다(조회수 증가). 없는 id면 404. */
export async function getPost(accessToken: string, postId: string): Promise<CommunityPostDetail> {
  return apiFetch<CommunityPostDetail>(`/api/v1/community/posts/${postId}`, accessToken);
}

export interface ListPostsParams {
  category?: string;
  tag?: string;
  keyword?: string;
  sort?: "popular";
  page?: number;
  size?: number;
}

/** 게시글 목록을 페이지 단위로 조회한다. */
export async function listPosts(
  accessToken: string,
  params: ListPostsParams = {},
): Promise<PageResponse<CommunityPostSummary>> {
  const searchParams = new URLSearchParams();
  if (params.category) searchParams.set("category", params.category);
  if (params.tag) searchParams.set("tag", params.tag);
  if (params.keyword) searchParams.set("keyword", params.keyword);
  if (params.sort) searchParams.set("sort", params.sort);
  if (params.page != null) searchParams.set("page", String(params.page));
  if (params.size != null) searchParams.set("size", String(params.size));
  const qs = searchParams.toString();
  return apiFetch<PageResponse<CommunityPostSummary>>(
    `/api/v1/community/posts${qs ? `?${qs}` : ""}`,
    accessToken,
  );
}
