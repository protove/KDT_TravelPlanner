"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/Select";
import { SearchBar } from "@/components/molecules/SearchBar";
import { CommunityPostCard, CommunityPostCardSkeleton } from "@/components/organisms/CommunityPostCard";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { getCategories, listPosts, type PageResponse } from "@/lib/api/community";
import type { CommunityCategory, CommunityPostSummary } from "@/lib/types/community";

const ALL_CATEGORY = "ALL";
const PAGE_SIZE = 10;

type SortOption = "latest" | "popular";

export default function CommunityPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);

  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  const [categoryTab, setCategoryTab] = React.useState(ALL_CATEGORY);
  const [sort, setSort] = React.useState<SortOption>("latest");
  const [keyword, setKeyword] = React.useState("");
  const [page, setPage] = React.useState(0);

  const [result, setResult] = React.useState<PageResponse<CommunityPostSummary> | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);

  const requestKey = `${accessToken ?? ""}:${categoryTab}:${sort}:${keyword}:${page}:${refreshKey}`;
  const isLoading = completedRequestKey !== requestKey;

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  React.useEffect(() => {
    let isCurrentRequest = true;

    listPosts(accessToken, {
      category: categoryTab === ALL_CATEGORY ? undefined : categoryTab,
      keyword: keyword.trim() || undefined,
      sort: sort === "popular" ? "popular" : undefined,
      page,
      size: PAGE_SIZE,
    })
      .then((res) => {
        if (!isCurrentRequest) return;
        setResult(res);
        setError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setError("게시글을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isCurrentRequest) setCompletedRequestKey(requestKey);
      });

    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, categoryTab, sort, keyword, page, refreshKey, requestKey]);

  function changeCategory(value: string) {
    setCategoryTab(value);
    setPage(0);
  }

  function changeSort(value: string) {
    setSort(value as SortOption);
    setPage(0);
  }

  function changeKeyword(value: string) {
    setKeyword(value);
    setPage(0);
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
      <SearchBar
        placeholder="키워드로 커뮤니티 글 검색"
        value={keyword}
        onChange={(e) => changeKeyword(e.target.value)}
        containerClassName="mb-4"
      />

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
          <Button variant="outline" onClick={() => setRefreshKey((k) => k + 1)}>
            다시 시도
          </Button>
        </div>
      ) : isLoading ? (
        <div className="flex flex-col gap-4">
          {Array.from({ length: 4 }, (_, i) => (
            <CommunityPostCardSkeleton key={i} />
          ))}
        </div>
      ) : !result || result.content.length === 0 ? (
        <div className="py-16 text-center text-sm text-muted-foreground">
          {activeCategoryLabel}에 게시글이 아직 없어요.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {result.content.map((post) => (
            <CommunityPostCard
              key={post.postId}
              post={post}
              categoryName={categoryName(post.categoryCode)}
              onClick={() => router.push(`/community/detail?id=${post.postId}`)}
            />
          ))}
        </div>
      )}

      {!error && !isLoading && result && result.totalPages > 1 && (
        <div className="mt-6 flex items-center justify-center gap-4">
          <Button
            variant="outline"
            size="icon"
            disabled={result.isFirst}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            aria-label="이전 페이지"
          >
            <Icon icon={ChevronLeft} size="sm" />
          </Button>
          <span className="text-sm text-muted-foreground">
            {result.page + 1} / {result.totalPages}
          </span>
          <Button
            variant="outline"
            size="icon"
            disabled={result.isLast}
            onClick={() => setPage((p) => p + 1)}
            aria-label="다음 페이지"
          >
            <Icon icon={ChevronRight} size="sm" />
          </Button>
        </div>
      )}
    </ListLayout>
  );
}
