// 댓글 작성/수정 입력창(CommentInput, CommentRow의 인라인 수정) 공통 — 최대 50줄까지만 허용한다.
export const MAX_COMMENT_LINES = 50;

/** 붙여넣기 등으로 한 번에 들어와도 동일하게 최대 줄 수까지만 남기고 잘라낸다. */
export function clampCommentLines(value: string): string {
  const lines = value.split("\n");
  return lines.length > MAX_COMMENT_LINES ? lines.slice(0, MAX_COMMENT_LINES).join("\n") : value;
}
