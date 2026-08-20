import { Heart, MessageCircle } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Badge } from "@/components/atoms/Badge";
import { Icon } from "@/components/atoms/Icon";
import { Skeleton } from "@/components/atoms/Skeleton";
import type { CommunityPostSummary } from "@/lib/types/community";
import { cn } from "@/lib/utils";

function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "방금 전";
  if (diffMin < 60) return `${diffMin}분 전`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}시간 전`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}일 전`;
  const d = new Date(iso);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export interface CommunityPostCardProps {
  post: CommunityPostSummary;
  categoryName: string;
  onClick?: () => void;
  className?: string;
}

function CommunityPostCard({ post, categoryName, onClick, className }: CommunityPostCardProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onClick?.();
      }}
      className={cn(
        "flex cursor-pointer flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-card transition-shadow hover:shadow-dialog",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <Badge variant="accent" className="shrink-0">
            {categoryName}
          </Badge>
          <div className="flex min-w-0 items-center gap-1.5">
            <Avatar className="h-6 w-6 shrink-0">
              {post.authorProfileImageUrl && (
                <AvatarImage src={post.authorProfileImageUrl} alt={post.authorNickname} />
              )}
              <AvatarFallback className="text-xs">{post.authorNickname.slice(0, 1)}</AvatarFallback>
            </Avatar>
            <span className="truncate text-xs font-semibold text-foreground">{post.authorNickname}</span>
          </div>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{formatRelativeTime(post.createdAt)}</span>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="break-words text-base font-bold text-foreground">{post.title}</p>
        <p className="truncate text-sm text-fg-secondary">{post.bodyPreview}</p>
      </div>

      <div className="border-t border-border pt-3" />

      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
          <Icon icon={Heart} size="sm" className="size-3.5" />
          {post.reactionCount.toLocaleString()}
        </span>
        <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
          <Icon icon={MessageCircle} size="sm" className="size-3.5" />
          {post.commentCount.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

function CommunityPostCardSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-card", className)}
    >
      <div className="flex items-center gap-2.5">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-6 w-6 rounded-full" />
        <Skeleton className="h-4 w-20" />
      </div>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-full" />
      </div>
      <div className="border-t border-border pt-3" />
      <div className="flex gap-3">
        <Skeleton className="h-4 w-8" />
        <Skeleton className="h-4 w-8" />
      </div>
    </div>
  );
}

export { CommunityPostCard, CommunityPostCardSkeleton };
