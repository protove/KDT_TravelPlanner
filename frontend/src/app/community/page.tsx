"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/Select";
import { SearchBar } from "@/components/molecules/SearchBar";
import { CommunityPostList } from "@/components/organisms/CommunityPostList";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { getCategories, listPosts } from "@/lib/api/community";
import type { CommunityCategory, CommunityPostSearchScope, CommunityPostSummary } from "@/lib/types/community";

const ALL_CATEGORY = "ALL";
const PAGE_SIZE = 10;

type SortOption = "latest" | "popular";

const SEARCH_SCOPE_OPTIONS: { value: CommunityPostSearchScope; label: string }[] = [
  { value: "ALL", label: "전체" },
  { value: "TITLE", label: "제목" },
  { value: "AUTHOR", label: "사용자" },
  { value: "CONTENT", label: "내용" },
  { value: "TAG", label: "태그" },
];

export default function CommunityPage() {
  return (
    <React.Suspense fallback={null}>
      <CommunityPageContent />
    </React.Suspense>
  );
}

function CommunityPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const accessToken = useAuthStore((s) => s.accessToken);

  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  // 상세로 갔다가 뒤로가기(브라우저 back, 상세 화면의 "커뮤니티" 링크)로 돌아왔을 때
  // 선택했던 카테고리 탭이 "전체"로 초기화되지 않도록 URL 쿼리(?category=)로 상태를 남긴다.
  const [categoryTab, setCategoryTab] = React.useState(() => searchParams.get("category") ?? ALL_CATEGORY);
  const [sort, setSort] = React.useState<SortOption>("latest");
  // keyword/searchScope는 실제 조회에 쓰이는 "확정된" 값이고, keywordDraft/searchScopeDraft는
  // 입력 중인 값이다 — 타이핑할 때마다, 혹은 스코프 드롭다운만 바꿔도 매번 서버로 요청이 나가는 걸
  // 막기 위해 검색창에서 Enter를 눌러야 확정값에 반영되고 그때 비로소 재조회가 일어난다.
  const [keyword, setKeyword] = React.useState("");
  const [searchScope, setSearchScope] = React.useState<CommunityPostSearchScope>("ALL");
  const [keywordDraft, setKeywordDraft] = React.useState("");
  const [searchScopeDraft, setSearchScopeDraft] = React.useState<CommunityPostSearchScope>("ALL");

  const [posts, setPosts] = React.useState<CommunityPostSummary[]>([]);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const requestKey = `${accessToken ?? ""}:${categoryTab}:${sort}:${keyword}:${searchScope}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  // 카테고리/정렬/검색어 또는 refreshKey가 바뀌면 첫 페이지부터 새로 조회한다 (/trips 목록과 동일한 패턴).
  React.useEffect(() => {
    let isCurrentRequest = true;

    listPosts(accessToken, {
      category: categoryTab === ALL_CATEGORY ? undefined : categoryTab,
      keyword: keyword.trim() || undefined,
      searchScope,
      sort: sort === "popular" ? "popular" : undefined,
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
  }, [accessToken, categoryTab, sort, keyword, searchScope, refreshKey, requestKey]);

  const loadMore = React.useCallback(() => {
    if (isLast || loadingMore || error || isLoading) return;

    const nextPage = page + 1;
    setLoadingMore(true);

    listPosts(accessToken, {
      category: categoryTab === ALL_CATEGORY ? undefined : categoryTab,
      keyword: keyword.trim() || undefined,
      searchScope,
      sort: sort === "popular" ? "popular" : undefined,
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
  }, [accessToken, categoryTab, sort, keyword, searchScope, page, isLast, loadingMore, error, isLoading]);

  // 목록 하단의 sentinel이 화면에 보이면 다음 페이지를 불러온다.
  React.useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore();
    });

    observer.observe(el);

    return () => observer.disconnect();
  }, [loadMore]);

  function changeCategory(value: string) {
    setCategoryTab(value);
    router.replace(value === ALL_CATEGORY ? "/community" : `/community?category=${value}`, {
      scroll: false,
    });
  }

  function changeSort(value: string) {
    setSort(value as SortOption);
  }

  function commitSearch() {
    setKeyword(keywordDraft);
    setSearchScope(searchScopeDraft);
  }

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") commitSearch();
  }

  function categoryName(code: string): string {
    return categories.find((c) => c.code === code)?.name ?? code;
  }

  const activeCategoryLabel = categoryTab === ALL_CATEGORY ? "전체" : categoryName(categoryTab);

  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">커뮤니티</h1>}
      actions={
        <Button onClick={() => router.push("/community/write")}>+ 새 글 작성</Button>
      }
    >
      <div className="mb-4 flex gap-2">
        <Select value={searchScopeDraft} onValueChange={(v) => setSearchScopeDraft(v as CommunityPostSearchScope)}>
          <SelectTrigger className="w-24 shrink-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEARCH_SCOPE_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SearchBar
          placeholder="키워드로 커뮤니티 글 검색 (Enter로 검색)"
          value={keywordDraft}
          onChange={(e) => setKeywordDraft(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          containerClassName="flex-1"
        />
      </div>

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <Tabs value={categoryTab} onValueChange={changeCategory}>
          <TabsList>
            <TabsTrigger value={ALL_CATEGORY}>전체</TabsTrigger>
            {categories.map((category) => (
              <TabsTrigger key={category.code} value={category.code}>
                {category.name}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <Select value={sort} onValueChange={changeSort}>
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="latest">최신순</SelectItem>
            <SelectItem value="popular">인기순</SelectItem>
          </SelectContent>
        </Select>
      </div>

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
        <CommunityPostList
          posts={posts.map((post) => ({
            id: post.postId,
            post,
            categoryName: categoryName(post.categoryCode),
            onClick: () => router.push(`/community/detail?id=${post.postId}`),
          }))}
          isLoading={isLoading}
          isLoadingMore={loadingMore}
          emptyMessage={`${activeCategoryLabel}에 게시글이 아직 없어요.`}
        />
      )}

      {!error && <div ref={sentinelRef} className="h-px" />}
    </ListLayout>
  );
}
