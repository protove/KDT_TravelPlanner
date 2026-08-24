import * as React from "react";
import { Trash2 } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface CommentRowProps {
  name: string;
  avatarColor?: string;
  /** 있으면 이미지를, 없으면 이름 첫 글자 fallback을 보여준다(CommunityPostCard의 작성자 아바타와 동일한 규칙). */
  avatarImageUrl?: string | null;
  timeLabel: string;
  text: string;
  /** 전달하면 삭제 버튼이 나타난다 — 작성자 본인 댓글에서만 넘겨줄 것(백엔드 isMine 기준). */
  onDelete?: () => void;
  deleting?: boolean;
  className?: string;
}

function CommentRow({
  name,
  avatarColor = "var(--brand-700)",
  avatarImageUrl,
  timeLabel,
  text,
  onDelete,
  deleting = false,
  className,
}: CommentRowProps) {
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
          </div>
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
        <p className="mt-1 text-[13px] text-fg-secondary">{text}</p>
      </div>
    </div>
  );
}

export { CommentRow };
