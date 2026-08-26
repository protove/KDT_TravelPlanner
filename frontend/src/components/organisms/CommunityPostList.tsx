import * as React from "react";
import {
  CommunityPostCard,
  CommunityPostCardSkeleton,
  type CommunityPostCardProps,
} from "@/components/organisms/CommunityPostCard";
import { cn } from "@/lib/utils";

export interface CommunityPostListItem extends Omit<CommunityPostCardProps, "className"> {
  id: string;
}

export interface CommunityPostListProps {
  posts: CommunityPostListItem[];
  isLoading?: boolean;
  isLoadingMore?: boolean;
  loadingCount?: number;
  emptyMessage?: string;
  className?: string;
}

function CommunityPostList({
  posts,
  isLoading = false,
  isLoadingMore = false,
  loadingCount = 4,
  emptyMessage = "게시글이 아직 없어요.",
  className,
}: CommunityPostListProps) {
  if (isLoading) {
    return (
      <div
        role="status"
        aria-label="게시글을 불러오는 중"
        className={cn("flex flex-col gap-4", className)}
      >
        {Array.from({ length: loadingCount }, (_, index) => (
          <CommunityPostCardSkeleton key={index} />
        ))}
      </div>
    );
  }

  if (posts.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-muted-foreground">{emptyMessage}</div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      {posts.map(({ id, ...post }) => (
        <CommunityPostCard key={id} {...post} />
      ))}
      {isLoadingMore && <CommunityPostCardSkeleton />}
    </div>
  );
}

export { CommunityPostList };
