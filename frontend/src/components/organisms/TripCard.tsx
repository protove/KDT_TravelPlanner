import * as React from "react";
import { Badge } from "@/components/atoms/Badge";
import { Avatar, AvatarFallback } from "@/components/atoms/Avatar";
import { cn } from "@/lib/utils";

export interface TripCardMember {
  initial: string;
  color: string;
}

export interface TripCardProps {
  title: string;
  dates: string;
  days: number;
  dday?: number | null;
  members?: TripCardMember[];
  isPast?: boolean;
  onClick?: () => void;
  className?: string;
}

function TripCard({ title, dates, days, dday, members = [], isPast = false, onClick, className }: TripCardProps) {
  const showDday = !isPast && dday != null;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick?.();
      }}
      className={cn(
        "cursor-pointer overflow-hidden rounded-xl bg-card shadow-card transition-shadow hover:shadow-dialog",
        className
      )}
    >
      <div
        className="relative flex h-[140px] items-center justify-center font-mono text-[11px] tracking-wide text-accent-foreground"
        style={{
          background:
            "repeating-linear-gradient(135deg, var(--brand-100), var(--brand-100) 10px, var(--brand-200) 10px, var(--brand-200) 20px)",
        }}
      >
        [ 여행 사진 ]
      </div>
      <div className="p-4">
        <div className="flex items-start justify-between gap-2.5">
          <div>
            <div className="text-base font-bold text-foreground">{title}</div>
            <div className="mt-0.5 text-sm text-muted-foreground">{dates}</div>
          </div>
          {showDday && (
            <Badge variant="accent" className="whitespace-nowrap">
              D-{dday}
            </Badge>
          )}
        </div>
        <div className="mt-3.5 flex items-center justify-between">
          <div className="flex">
            {members.map((m, i) => (
              <Avatar key={i} className="h-[26px] w-[26px] ring-2 ring-background" style={i > 0 ? { marginLeft: "-8px" } : undefined}>
                <AvatarFallback className="text-xs text-white" style={{ background: m.color }}>
                  {m.initial}
                </AvatarFallback>
              </Avatar>
            ))}
          </div>
          {isPast ? (
            <span className="text-sm font-bold text-primary">앨범 보기</span>
          ) : (
            <span className="text-xs text-muted-foreground">{days}일 일정</span>
          )}
        </div>
      </div>
    </div>
  );
}

export { TripCard };
