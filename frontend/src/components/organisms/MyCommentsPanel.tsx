"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Checkbox } from "@/components/atoms/Checkbox";
import { Skeleton } from "@/components/atoms/Skeleton";
import { SearchBar } from "@/components/molecules/SearchBar";
import { SearchPeriodSelect } from "@/components/molecules/SearchPeriodSelect";
import { listMyComments } from "@/lib/api/community";
import type { MyCommentResponse } from "@/lib/types/community";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils/formatRelativeTime";
import { DEFAULT_SEARCH_PERIOD, resolveSearchPeriod, type SearchPeriodPreset } from "@/lib/utils/searchPeriod";

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

// MyPostsPanel과 동일한 sentinel + IntersectionObserver 무한 스크롤 패턴, 그리고 동일한
// Enter로 검색 확정 패턴(community/page.tsx 참고).
function MyCommentsPanel({ accessToken }: MyCommentsPanelProps) {
  const router = useRouter();

  const [comments, setComments] = React.useState<MyCommentResponse[]>([]);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);

  const [keyword, setKeyword] = React.useState("");
  const [keywordDraft, setKeywordDraft] = React.useState("");
  const [period, setPeriod] = React.useState<SearchPeriodPreset>(DEFAULT_SEARCH_PERIOD);
  // 기본값은 false — 내가 삭제한 댓글은 마이페이지에서도 기본으로는 숨긴다.
  const [includeDeleted, setIncludeDeleted] = React.useState(false);

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const { periodStart, periodEnd } = resolveSearchPeriod(period);
  const requestKey = `${accessToken}:${keyword}:${period}:${includeDeleted}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    let isCurrentRequest = true;

    listMyComments(accessToken, {
      keyword: keyword.trim() || undefined,
      periodStart,
      periodEnd,
      includeDeleted,
      page: 0,
      size: PAGE_SIZE,
    })
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, keyword, includeDeleted, refreshKey, requestKey]);

  const loadMore = React.useCallback(() => {
    if (isLast || loadingMore || error || isLoading) return;

    const nextPage = page + 1;
    setLoadingMore(true);

    listMyComments(accessToken, {
      keyword: keyword.trim() || undefined,
      periodStart,
      periodEnd,
      includeDeleted,
      page: nextPage,
      size: PAGE_SIZE,
    })
      .then((res) => {
        setComments((prev) => [...prev, ...res.content]);
        setPage(nextPage);
        setIsLast(res.isLast);
      })
      .catch(() => setIsLast(true))
      .finally(() => setLoadingMore(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken, keyword, period, includeDeleted, page, isLast, loadingMore, error, isLoading]);

  React.useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore();
    });

    observer.observe(el);

    return () => observer.disconnect();
  }, [loadMore]);

  function commitSearch() {
    setKeyword(keywordDraft);
  }

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") commitSearch();
  }

  return (
    <>
      <div className="mb-3 flex gap-2">
        <SearchPeriodSelect value={period} onValueChange={setPeriod} />
        <SearchBar
          placeholder="내가 쓴 댓글 검색 (Enter로 검색)"
          value={keywordDraft}
          onChange={(e) => setKeywordDraft(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          containerClassName="flex-1"
        />
      </div>

      <label className="mb-4 flex w-fit cursor-pointer items-center gap-2 text-sm text-muted-foreground">
        <Checkbox
          checked={includeDeleted}
          onCheckedChange={(checked) => setIncludeDeleted(checked === true)}
        />
        삭제한 댓글도 보기
      </label>

      {error ? (
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
      ) : (
        <>
          <div className="flex flex-col gap-3">
            {isLoading ? (
              Array.from({ length: 4 }, (_, i) => <MyCommentCardSkeleton key={i} />)
            ) : comments.length === 0 ? (
              <div className="py-16 text-center text-sm text-muted-foreground">
                {keyword ? "검색 결과가 없어요." : "아직 작성한 댓글이 없어요."}
              </div>
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
      )}
    </>
  );
}

export { MyCommentsPanel };
