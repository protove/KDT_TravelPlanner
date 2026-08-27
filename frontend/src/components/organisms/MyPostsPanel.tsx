"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Checkbox } from "@/components/atoms/Checkbox";
import { SearchBar } from "@/components/molecules/SearchBar";
import { SearchPeriodSelect } from "@/components/molecules/SearchPeriodSelect";
import { CommunityPostList } from "@/components/organisms/CommunityPostList";
import { getCategories, listMyPosts } from "@/lib/api/community";
import { DEFAULT_SEARCH_PERIOD, resolveSearchPeriod, type SearchPeriodPreset } from "@/lib/utils/searchPeriod";
import type { CommunityCategory, CommunityPostSummary } from "@/lib/types/community";

const PAGE_SIZE = 10;

export interface MyPostsPanelProps {
  accessToken: string;
}

// /trips, /community 목록과 동일한 sentinel + IntersectionObserver 무한 스크롤 패턴, 그리고
// 동일한 Enter로 검색 확정 패턴(community/page.tsx 참고) — keyword/keywordDraft를 분리해
// 타이핑할 때마다 서버로 요청이 나가지 않게 한다. period는 카테고리/정렬처럼 선택 즉시 반영.
function MyPostsPanel({ accessToken }: MyPostsPanelProps) {
  const router = useRouter();

  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  const [posts, setPosts] = React.useState<CommunityPostSummary[]>([]);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);

  const [keyword, setKeyword] = React.useState("");
  const [keywordDraft, setKeywordDraft] = React.useState("");
  const [period, setPeriod] = React.useState<SearchPeriodPreset>(DEFAULT_SEARCH_PERIOD);
  // 기본값은 false — 내가 삭제한 글은 마이페이지에서도 기본으로는 숨긴다.
  const [includeDeleted, setIncludeDeleted] = React.useState(false);

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const { periodStart, periodEnd } = resolveSearchPeriod(period);
  const requestKey = `${accessToken}:${keyword}:${period}:${includeDeleted}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  React.useEffect(() => {
    let isCurrentRequest = true;

    listMyPosts(accessToken, {
      keyword: keyword.trim() || undefined,
      periodStart,
      periodEnd,
      includeDeleted,
      page: 0,
      size: PAGE_SIZE,
    })
      .then((res) => {
        if (!isCurrentRequest) return;
        setPosts(res.content);
        setPage(0);
        setIsLast(res.isLast);
        setError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setError("게시글을 불러오지 못했습니다.");
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

    listMyPosts(accessToken, {
      keyword: keyword.trim() || undefined,
      periodStart,
      periodEnd,
      includeDeleted,
      page: nextPage,
      size: PAGE_SIZE,
    })
      .then((res) => {
        setPosts((prev) => [...prev, ...res.content]);
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

  function categoryName(code: string): string {
    return categories.find((c) => c.code === code)?.name ?? code;
  }

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
          placeholder="내가 쓴 글 검색 (Enter로 검색)"
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
        삭제한 글도 보기
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
          <CommunityPostList
            posts={posts.map((post) => ({
              id: post.postId,
              post,
              categoryName: categoryName(post.categoryCode),
              onClick: () => router.push(`/community/detail?id=${post.postId}`),
            }))}
            isLoading={isLoading}
            isLoadingMore={loadingMore}
            emptyMessage={keyword ? "검색 결과가 없어요." : "아직 작성한 게시글이 없어요."}
          />
          <div ref={sentinelRef} className="h-px" />
        </>
      )}
    </>
  );
}

export { MyPostsPanel };
