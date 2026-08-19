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
  isMine: boolean;
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
}

/** 수정 요청. PatchField 방식 — 보낸 필드만 반영, version은 낙관적 락이라 항상 필수. */
export interface CommunityPostUpdatePatch {
  title?: string;
  bodyJson?: TiptapDocument;
  /** 보내면 기존 태그 전체를 이걸로 교체(부분 추가 아님) */
  tags?: string[];
  version: number;
}

export interface CommentResponse {
  commentId: string;
  authorNickname: string;
  authorProfileImageUrl: string | null;
  content: string;
  createdAt: string;
  isMine: boolean;
}

export interface CommentCreateRequest {
  content: string;
}
