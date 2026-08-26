"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Skeleton } from "@/components/atoms/Skeleton";
import { listMyComments } from "@/lib/api/community";
import type { MyCommentResponse } from "@/lib/types/community";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils/formatRelativeTime";

const PAGE_SIZE = 10;

export interface MyCommentsPanelProps {
  accessToken: string;
}

function MyCommentCard({ comment, onClick }: { comment: MyCommentResponse; onClick: () => void }) {
  // 댓글 자체를 지웠거나(deletedAt), 댓글은 안 지웠는데 글이 삭제된 경우(postDeletedAt) 둘 다
  // 상세로 들어가면 404라 클릭을 막는다.
  const isDeleted = Boolean(comment.deletedAt);
  const isPostDeleted = Boolean(comment.postDeletedAt);
  const disabled = isDeleted || isPostDeleted;

  return (
    <div
      role={disabled ? undefined : "button"}
      tabIndex={disabled ? undefined : 0}
      onClick={disabled ? undefined : onClick}
      onKeyDown={
        disabled
          ? undefined
          : (event) => {
              if (event.key === "Enter" || event.key === " ") onClick();
            }
      }
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border border-border bg-card p-4 shadow-card transition-shadow",
        disabled ? "opacity-60" : "cursor-pointer hover:shadow-dialog",
      )}
    >
      <div className="flex items-center gap-1.5">
        <p className="truncate text-xs font-semibold text-muted-foreground">{comment.postTitle}</p>
        {isDeleted && (
          <Badge variant="destructive" className="shrink-0">
            삭제한 댓글
          </Badge>
        )}
        {!isDeleted && isPostDeleted && (
          <Badge variant="destructive" className="shrink-0">
            삭제된 글
          </Badge>
        )}
      </div>
      <p className="line-clamp-2 break-words text-sm text-foreground">{comment.content}</p>
      <span className="text-xs text-fg-muted">
        {formatRelativeTime(comment.createdAt)}
        {comment.updatedAt && " (수정됨)"}
      </span>
    </div>
  );
}

function MyCommentCardSkeleton() {
  return (
    <div aria-hidden="true" className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 shadow-card">
      <Skeleton className="h-3.5 w-24" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

// MyPostsPanel과 동일한 sentinel + IntersectionObserver 무한 스크롤 패턴.
function MyCommentsPanel({ accessToken }: MyCommentsPanelProps) {
  const router = useRouter();

  const [comments, setComments] = React.useState<MyCommentResponse[]>([]);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const requestKey = `${accessToken}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    let isCurrentRequest = true;

    listMyComments(accessToken, { page: 0, size: PAGE_SIZE })
      .then((res) => {
        if (!isCurrentRequest) return;
        setComments(res.content);
        setPage(0);
        setIsLast(res.isLast);
        setError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setError("댓글을 불러오지 못했습니다.");
        setIsLast(true);
      })
      .finally(() => {
        if (isCurrentRequest) setCompletedRequestKey(requestKey);
      });

    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, refreshKey, requestKey]);

  const loadMore = React.useCallback(() => {
    if (isLast || loadingMore || error || isLoading) return;

    const nextPage = page + 1;
    setLoadingMore(true);

    listMyComments(accessToken, { page: nextPage, size: PAGE_SIZE })
      .then((res) => {
        setComments((prev) => [...prev, ...res.content]);
        setPage(nextPage);
        setIsLast(res.isLast);
      })
      .catch(() => setIsLast(true))
      .finally(() => setLoadingMore(false));
  }, [accessToken, page, isLast, loadingMore, error, isLoading]);

  React.useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore();
    });

    observer.observe(el);

    return () => observer.disconnect();
  }, [loadMore]);

  if (error) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button
          variant="outline"
          onClick={() => {
            setError(null);
            setRefreshKey((k) => k + 1);
          }}
        >
          다시 시도
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col gap-3">
        {isLoading ? (
          Array.from({ length: 4 }, (_, i) => <MyCommentCardSkeleton key={i} />)
        ) : comments.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted-foreground">아직 작성한 댓글이 없어요.</div>
        ) : (
          <>
            {comments.map((comment) => (
              <MyCommentCard
                key={comment.commentId}
                comment={comment}
                onClick={() => router.push(`/community/detail?id=${comment.postId}`)}
              />
            ))}
            {loadingMore && <MyCommentCardSkeleton />}
          </>
        )}
      </div>
      <div ref={sentinelRef} className="h-px" />
    </>
  );
}

export { MyCommentsPanel };
