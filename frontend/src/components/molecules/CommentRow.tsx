"use client";

import * as React from "react";
import { Heart, Pencil, Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Textarea } from "@/components/atoms/Textarea";
import { clampCommentLines } from "@/lib/utils/clampCommentLines";
import { cn } from "@/lib/utils";

export interface CommentRowProps {
  name: string;
  avatarColor?: string;
  /** 있으면 이미지를, 없으면 이름 첫 글자 fallback을 보여준다(CommunityPostCard의 작성자 아바타와 동일한 규칙). */
  avatarImageUrl?: string | null;
  timeLabel: string;
  text: string;
  /** true면 이름/시간 옆에 "(수정됨)" 표시. */
  edited?: boolean;
  reactionCount: number;
  isReacted: boolean;
  /** 전달하면 좋아요 버튼이 클릭 가능해진다 — 비로그인이면 undefined로 넘겨서 보기만 가능하게 할 것. */
  onToggleReaction?: () => void;
  reactionPending?: boolean;
  /** 전달하면 삭제 버튼이 나타난다 — 작성자 본인 댓글에서만 넘겨줄 것(백엔드 isMine 기준). */
  onDelete?: () => void;
  deleting?: boolean;
  /**
   * 전달하면 수정 버튼이 나타난다 — 작성자 본인 댓글에서만. 저장 성공 시 true를 반환해야
   * 인라인 편집 모드가 닫힌다(false를 반환하면 편집 모드를 유지 — 부모가 에러를 별도로 보여줄 것).
   */
  onEdit?: (newContent: string) => Promise<boolean>;
  editSubmitting?: boolean;
  maxLength?: number;
  className?: string;
}

function CommentRow({
  name,
  avatarColor = "var(--brand-700)",
  avatarImageUrl,
  timeLabel,
  text,
  edited = false,
  reactionCount,
  isReacted,
  onToggleReaction,
  reactionPending = false,
  onDelete,
  deleting = false,
  onEdit,
  editSubmitting = false,
  maxLength,
  className,
}: CommentRowProps) {
  // draft는 편집 모드일 때만 화면에 쓰인다(아래 JSX 참고) — 편집을 시작/취소할 때마다
  // startEdit()/cancelEdit()이 draft를 text로 다시 맞춰주므로, 편집 중이 아닐 때 draft를
  // text와 동기화하는 별도 effect는 불필요하다(react-hooks/set-state-in-effect 위반이기도 함).
  const [isEditing, setIsEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(text);

  function startEdit() {
    setDraft(text);
    setIsEditing(true);
  }

  function cancelEdit() {
    setIsEditing(false);
    setDraft(text);
  }

  async function saveEdit() {
    const next = draft.trim();
    if (!next || !onEdit || editSubmitting) return;
    const success = await onEdit(next);
    if (success) setIsEditing(false);
  }

  const showActions = !isEditing && (onEdit || onDelete);

  return (
    <div className={cn("flex gap-2.5", className)}>
      <Avatar className="h-[30px] w-[30px] shrink-0">
        {avatarImageUrl && <AvatarImage src={avatarImageUrl} alt={name} />}
        <AvatarFallback className="text-xs text-white" style={{ background: avatarColor }}>
          {name.slice(0, 1)}
        </AvatarFallback>
      </Avatar>
      <div className="flex-1 rounded-lg bg-card px-3.5 py-2.5 shadow-card">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-baseline gap-2">
            <span className="text-[13px] font-bold text-foreground">{name}</span>
            <span className="text-xs text-muted-foreground">{timeLabel}</span>
            {edited && <span className="text-xs text-muted-foreground">(수정됨)</span>}
          </div>
          {showActions && (
            <div className="flex shrink-0 items-center gap-1">
              {onEdit && (
                <button
                  type="button"
                  title="댓글 수정"
                  onClick={startEdit}
                  className="flex h-[22px] w-[22px] shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  <Icon icon={Pencil} size="sm" className="size-3.5" aria-label="댓글 수정" />
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  title="댓글 삭제"
                  onClick={onDelete}
                  disabled={deleting}
                  className="flex h-[22px] w-[22px] shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Icon icon={Trash2} size="sm" className="size-3.5" aria-label="댓글 삭제" />
                </button>
              )}
            </div>
          )}
        </div>

        {isEditing ? (
          <div className="mt-1.5 flex flex-col gap-2">
            <Textarea
              value={draft}
              onChange={(e) => setDraft(clampCommentLines(e.target.value))}
              maxLength={maxLength}
              rows={2}
              disabled={editSubmitting}
              className="min-h-[60px] resize-y text-[13px]"
            />
            <div className="flex justify-end gap-2">
              <Button type="button" size="sm" variant="outline" onClick={cancelEdit} disabled={editSubmitting}>
                취소
              </Button>
              <Button type="button" size="sm" onClick={saveEdit} disabled={editSubmitting || !draft.trim()}>
                {editSubmitting ? "저장 중..." : "저장"}
              </Button>
            </div>
          </div>
        ) : (
          <p className="mt-1 whitespace-pre-wrap break-words text-[13px] text-fg-secondary">{text}</p>
        )}

        {!isEditing && (
          <div className="mt-2 flex items-center gap-1">
            <button
              type="button"
              title="좋아요"
              onClick={onToggleReaction}
              disabled={!onToggleReaction || reactionPending}
              className={cn(
                "flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold",
                isReacted ? "text-destructive" : "text-muted-foreground",
                onToggleReaction ? "cursor-pointer hover:bg-muted" : "cursor-default",
              )}
            >
              <Icon icon={Heart} size="sm" className={cn("size-3.5", isReacted && "fill-current")} aria-label="좋아요" />
              {reactionCount.toLocaleString()}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export { CommentRow };
