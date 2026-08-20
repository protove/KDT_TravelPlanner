import { http, HttpResponse } from "msw";

import type { CommunityCategory } from "@/lib/types/community";

/** 시드값 추정치. Figma 탭 라벨 확정되면 바뀔 수 있음(docs/community-api-contract.md 8절). */
const CATEGORIES: CommunityCategory[] = [
  { code: "TRAVEL_REVIEW", name: "여행후기", sortOrder: 1 },
  { code: "FREE", name: "자유", sortOrder: 2 },
  { code: "QNA", name: "질문답변", sortOrder: 3 },
  { code: "NOTICE", name: "공지사항", sortOrder: 4 },
];

const EMPTY_PAGE = {
  content: [],
  page: 0,
  size: 10,
  totalElements: 0,
  totalPages: 0,
  isFirst: true,
  isLast: true,
};

/** 아직 구현되지 않은 핸들러의 임시 응답. 다음 브랜치들에서 각자 실제 구현으로 교체한다. */
function notImplemented() {
  return HttpResponse.json(
    { code: "NOT_IMPLEMENTED", message: "아직 구현되지 않은 mock 핸들러입니다.", requestId: "" },
    { status: 501 },
  );
}

export const communityHandlers = [
  http.get("*/api/v1/community/categories", () => HttpResponse.json({ data: CATEGORIES })),

  // 아래는 자리만 남겨둔 임시 핸들러 — 각 담당 브랜치에서 실제 구현으로 교체
  http.get("*/api/v1/community/tags", () => HttpResponse.json({ data: [] })),
  http.get("*/api/v1/community/posts", () => HttpResponse.json({ data: EMPTY_PAGE })),
  http.post("*/api/v1/community/posts", () => notImplemented()),
  http.get("*/api/v1/community/posts/:postId", () => notImplemented()),
  http.patch("*/api/v1/community/posts/:postId", () => notImplemented()),
  http.delete("*/api/v1/community/posts/:postId", () => notImplemented()),
  http.get("*/api/v1/community/posts/:postId/comments", () => HttpResponse.json({ data: [] })),
  http.post("*/api/v1/community/posts/:postId/comments", () => notImplemented()),
  http.delete("*/api/v1/community/comments/:commentId", () => notImplemented()),
  http.put("*/api/v1/community/posts/:postId/reactions/:type", () => notImplemented()),
];
