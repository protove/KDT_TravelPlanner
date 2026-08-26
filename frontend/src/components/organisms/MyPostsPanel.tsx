"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { CommunityPostList } from "@/components/organisms/CommunityPostList";
import { getCategories, listMyPosts } from "@/lib/api/community";
import type { CommunityCategory, CommunityPostSummary } from "@/lib/types/community";

const PAGE_SIZE = 10;

export interface MyPostsPanelProps {
  accessToken: string;
}

// /trips, /community 목록과 동일한 sentinel + IntersectionObserver 무한 스크롤 패턴 —
// 카테고리/정렬/검색 필터가 없다는 점만 다르다(항상 본인 글 전체).
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

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const requestKey = `${accessToken}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  React.useEffect(() => {
    let isCurrentRequest = true;

    listMyPosts(accessToken, { page: 0, size: PAGE_SIZE })
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
  }, [accessToken, refreshKey, requestKey]);

  const loadMore = React.useCallback(() => {
    if (isLast || loadingMore || error || isLoading) return;

    const nextPage = page + 1;
    setLoadingMore(true);

    listMyPosts(accessToken, { page: nextPage, size: PAGE_SIZE })
      .then((res) => {
        setPosts((prev) => [...prev, ...res.content]);
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

  function categoryName(code: string): string {
    return categories.find((c) => c.code === code)?.name ?? code;
  }

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
      <CommunityPostList
        posts={posts.map((post) => ({
          id: post.postId,
          post,
          categoryName: categoryName(post.categoryCode),
          onClick: () => router.push(`/community/detail?id=${post.postId}`),
        }))}
        isLoading={isLoading}
        isLoadingMore={loadingMore}
        emptyMessage="아직 작성한 게시글이 없어요."
      />
      <div ref={sentinelRef} className="h-px" />
    </>
  );
}

export { MyPostsPanel };
