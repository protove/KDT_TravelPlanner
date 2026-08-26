/** 백엔드 community_category 테이블과 대응. GET /api/v1/community/categories 응답. */
export interface CommunityCategory {
  code: string;
  name: string;
  sortOrder: number;
}

/** Tiptap 커스텀 마크. StarterKit의 bold/italic + Underline extension만 허용(docs/community-api-contract.md 6-1). */
export type TiptapMarkType = "bold" | "italic" | "underline";

export interface TiptapMark {
  type: TiptapMarkType;
}

export type TiptapTextAlign = "left" | "center" | "right";

export interface TiptapTextNode {
  type: "text";
  text: string;
  marks?: TiptapMark[];
}

export interface TiptapHardBreakNode {
  type: "hardBreak";
}

export type TiptapInlineNode = TiptapTextNode | TiptapHardBreakNode;

export interface TiptapParagraphNode {
  type: "paragraph";
  attrs?: { textAlign?: TiptapTextAlign };
  content?: TiptapInlineNode[];
}

export interface TiptapHeadingNode {
  type: "heading";
  attrs: { level: 1 | 2 | 3; textAlign?: TiptapTextAlign };
  content?: TiptapInlineNode[];
}

export interface TiptapListItemNode {
  type: "listItem";
  content: TiptapParagraphNode[];
}

export interface TiptapBulletListNode {
  type: "bulletList";
  content: TiptapListItemNode[];
}

export interface TiptapImageNode {
  type: "image";
  attrs: { src: string; alt?: string | null };
}

export type TiptapBlockNode =
  | TiptapParagraphNode
  | TiptapHeadingNode
  | TiptapBulletListNode
  | TiptapImageNode;

/** 허용된 5개 노드 타입(paragraph/heading/bulletList/listItem/image)만 담는 Tiptap 문서. bodyJson 저장 포맷. */
export interface TiptapDocument {
  type: "doc";
  content: TiptapBlockNode[];
}

/**
 * 여행후기 작성 시점에 고정하는 일정 스냅샷. Tiptap 문서가 아니라 일정 자체의 원래 모양
 * (day별 장소 목록 + 좌표)을 그대로 담는다 — bodyJson과는 완전히 다른, 독립된 데이터.
 * ItinerarySnapshotCard가 이 값을 ScheduleBoard/MapPanel에 그대로 흘려보내 그린다.
 */
export interface ItinerarySnapshotItem {
  timelineItemId: string;
  name: string;
  category: string;
  foodSubcategory?: string | null;
  visitOrder: number;
  /** /map-points에서 조회된 좌표. 없으면(구글 place 매핑 실패 등) 지도에 마커로 안 찍힌다. */
  lat?: number;
  lng?: number;
}

export interface ItinerarySnapshotDay {
  dayNumber: number;
  visitDate: string | null;
  items: ItinerarySnapshotItem[];
}

export interface ItinerarySnapshot {
  title: string;
  startDate: string;
  endDate: string;
  days: ItinerarySnapshotDay[];
  /** dayNumber가 배정되지 않은 항목. day가 없어 좌표 조회(/map-points)가 불가해 lat/lng는 항상 없다. */
  unassigned: ItinerarySnapshotItem[];
}

/** GET /posts의 keyword 매칭 대상. 백엔드 CommunityPostService.VALID_SEARCH_SCOPES와 동일. */
export type CommunityPostSearchScope = "ALL" | "TITLE" | "AUTHOR" | "CONTENT" | "TAG";

/** 목록 카드(community-board / PostCard)용 요약. */
export interface CommunityPostSummary {
  postId: string;
  categoryCode: string;
  title: string;
  bodyPreview: string;
  tags: string[];
  authorNickname: string;
  authorProfileImageUrl: string | null;
  viewCount: number;
  commentCount: number;
  reactionCount: number;
  sourceTravelId: string | null;
  createdAt: string;
}

/** 상세(community-detail) 응답. 목록 요약 필드 + 본문 + 내 글 여부. */
export interface CommunityPostDetail extends CommunityPostSummary {
  bodyJson: TiptapDocument;
  /**
   * 후기 작성 시점에 고정된 일정 스냅샷. sourceTravelId로 일정을 불러와 쓴 후기에만 존재하고,
   * 이후 원본 여행이 바뀌어도 이 값은 그대로 유지된다(불변, 수정 API 없음). 없으면 null.
   */
  itinerarySnapshotJson: ItinerarySnapshot | null;
  isMine: boolean;
  /** 로그인한 요청자가 이 게시글에 좋아요를 눌렀는지. 비로그인 조회 시 항상 false. */
  isReacted: boolean;
  /** PATCH /posts/{postId}의 낙관적 락에 그대로 되돌려 보내야 하는 값. */
  version: number;
}

/** PUT /posts/{postId}/reactions/LIKE 응답. */
export interface CommunityPostReactionResponse {
  reactionCount: number;
  isReacted: boolean;
}

/** 작성(community-write 등 공통) 요청. */
export interface CommunityPostCreateRequest {
  categoryCode: string;
  title: string;
  bodyJson: TiptapDocument;
  /** 최대 5개, 개당 1~20자 (docs/community-api-contract.md 4절) */
  tags?: string[];
  /** 여행후기이고 일정 기반으로 썼을 때만 */
  sourceTravelId?: string;
  /** sourceTravelId로 일정을 불러와 후기를 쓸 때만 함께 보낸다. 저장 후에는 불변. */
  itinerarySnapshotJson?: ItinerarySnapshot;
}

/** 수정 요청. PatchField 방식 — 보낸 필드만 반영, version은 낙관적 락이라 항상 필수. */
export interface CommunityPostUpdatePatch {
  title?: string;
  bodyJson?: TiptapDocument;
  /** 보내면 기존 태그 전체를 이걸로 교체(부분 추가 아님) */
  tags?: string[];
  version: number;
}

// community-api-contract.md 1절 CommentResponse 기반 + 댓글 좋아요/수정 기능 추가로 확장한 필드
// (updatedAt/reactionCount/isReacted — 계약 문서에는 아직 반영 안 됨, backend CommentResponse.kt와 동일).
export interface CommentResponse {
  commentId: string;
  authorNickname: string;
  authorProfileImageUrl: string | null;
  content: string;
  createdAt: string;
  /** null이면 한 번도 수정되지 않은 댓글. */
  updatedAt: string | null;
  reactionCount: number;
  /** 로그인한 요청자가 이 댓글에 좋아요를 눌렀는지. 비로그인 조회 시 항상 false. */
  isReacted: boolean;
  isMine: boolean;
}

export interface CommentCreateRequest {
  content: string;
}

/** PATCH /comments/{commentId} 요청. 필드가 CommentCreateRequest와 동일해서 별도 타입을 만들지 않고 재사용한다. */
export type CommentUpdateRequest = CommentCreateRequest;
