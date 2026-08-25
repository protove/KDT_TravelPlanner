import { apiFetch } from "@/lib/api/client";
import type {
  CommentCreateRequest,
  CommentResponse,
  CommentUpdateRequest,
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
export async function getCategories(accessToken?: string | null): Promise<CommunityCategory[]> {
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
export async function getPost(accessToken: string | null | undefined, postId: string): Promise<CommunityPostDetail> {
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

/** 게시글 목록을 페이지 단위로 조회한다(인증 불필요). */
export async function listPosts(
  accessToken: string | null | undefined,
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

/** 게시글의 댓글 목록을 조회한다(단일 depth, 페이지네이션 없음, 인증 불필요 — 로그인 상태면 isMine이 채워진다). */
export async function getComments(
  accessToken: string | null | undefined,
  postId: string,
): Promise<CommentResponse[]> {
  return apiFetch<CommentResponse[]>(`/api/v1/community/posts/${postId}/comments`, accessToken);
}

/** 댓글을 작성한다. 로그인 필요. */
export async function createComment(
  accessToken: string,
  postId: string,
  request: CommentCreateRequest,
): Promise<CommentResponse> {
  return apiFetch<CommentResponse>(`/api/v1/community/posts/${postId}/comments`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** 댓글 내용을 수정한다. 작성자 본인만 가능. */
export async function updateComment(
  accessToken: string,
  commentId: string,
  request: CommentUpdateRequest,
): Promise<CommentResponse> {
  return apiFetch<CommentResponse>(`/api/v1/community/comments/${commentId}`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** 댓글을 삭제한다(soft delete). 작성자 본인만 가능. */
export async function deleteComment(accessToken: string, commentId: string): Promise<void> {
  await apiFetch<unknown>(`/api/v1/community/comments/${commentId}`, accessToken, {
    method: "DELETE",
  });
}

/** 댓글 좋아요를 토글한다(이미 눌렀으면 취소). 로그인 필요. */
export async function toggleCommentReaction(accessToken: string, commentId: string): Promise<CommentResponse> {
  return apiFetch<CommentResponse>(`/api/v1/community/comments/${commentId}/reactions/LIKE`, accessToken, {
    method: "PUT",
  });
}
