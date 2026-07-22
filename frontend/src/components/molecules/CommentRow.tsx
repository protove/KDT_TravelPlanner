import * as React from "react";
import { Avatar, AvatarFallback } from "@/components/atoms/Avatar";
import { cn } from "@/lib/utils";

export interface CommentRowProps {
  name: string;
  avatarColor?: string;
  timeLabel: string;
  text: string;
  className?: string;
}

function CommentRow({ name, avatarColor = "var(--brand-700)", timeLabel, text, className }: CommentRowProps) {
    return (
    <div className={cn("flex gap-2.5", className)}>
      <Avatar className="h-[30px] w-[30px] shrink-0">
        <AvatarFallback className="text-xs text-white" style={{ background: avatarColor }}>
          {name.slice(0, 1)}
        </AvatarFallback>
      </Avatar>
      <div className="flex-1 rounded-lg bg-card px-3.5 py-2.5 shadow-card">
        <div className="flex items-baseline gap-2">
          <span className="text-[13px] font-bold text-foreground">{name}</span>
          <span className="text-xs text-muted-foreground">{timeLabel}</span>
        </div>
        <p className="mt-1 text-[13px] text-fg-secondary">{text}</p>
      </div>
    </div>
  );
}

export { CommentRow };
