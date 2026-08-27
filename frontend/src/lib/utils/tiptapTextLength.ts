import type { TiptapDocument } from "@/lib/types/community";

// 재귀 순회용 느슨한 노드 형태 — TiptapBlockNode/TiptapInlineNode 유니온을 그대로 쓰면
// listItem처럼 유니온에 없는 중간 노드 타입 때문에 재귀 시그니처가 맞지 않아 이 형태로 순회한다.
interface AnyTiptapNode {
  type: string;
  text?: string;
  content?: AnyTiptapNode[];
}

// 백엔드 TiptapBodyJsonValidator.validate()와 동일하게 text 노드의 글자 수만 합산한다
// (마크업 구조는 카운트에 안 들어감). 글자수 카운터/제출 전 클라이언트 측 검증에 사용.
function collectLength(node: AnyTiptapNode): number {
  if (node.type === "text") return node.text?.length ?? 0;
  if (!node.content) return 0;
  return node.content.reduce((sum, child) => sum + collectLength(child), 0);
}

export function getTiptapTextLength(doc: TiptapDocument): number {
  return collectLength(doc as unknown as AnyTiptapNode);
}
