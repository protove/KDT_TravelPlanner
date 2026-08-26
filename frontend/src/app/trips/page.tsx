"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/Select";
import { TripList } from "@/components/organisms/TripList";
import { NewTripModal } from "@/components/organisms/NewTripModal";
import { SearchBar } from "@/components/molecules/SearchBar";
import { ListLayout } from "@/components/templates/ListLayout";
import { TripsPageSkeleton } from "@/components/templates/TripsPageSkeleton";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { fetchTravels, type TravelSearchScope, type TravelSummary } from "@/lib/api/travel";
import type { TripListItem } from "@/components/organisms/TripList";

type ListTab = "mine" | "shared";

const PAGE_SIZE = 20;

const SEARCH_SCOPE_OPTIONS: { value: TravelSearchScope; label: string }[] = [
  { value: "ALL", label: "전체" },
  { value: "TITLE", label: "제목" },
  { value: "DESCRIPTION", label: "설명" },
  { value: "DESTINATION", label: "여행지" },
];
const PREVIEW_THUMBNAILS = [
  "/images/trips/tokyo-thumbnail.png",
  "/images/trips/busan-thumbnail.png",
  "/images/trips/jeju-thumbnail.png",
] as const;

const PREVIEW_TRAVELS: TravelSummary[] = [
  {
    travelId: "preview-tokyo",
    title: "도쿄 벚꽃 여행",
    startDate: "2026-04-02",
    endDate: "2026-04-05",
    countryId: 1,
    cityId: 1,
    participantCount: 2,
    permission: "OWNER",
    updatedAt: "2026-07-27T00:00:00Z",
  },
  {
    travelId: "preview-busan",
    title: "부산 바다 여행",
    startDate: "2026-08-14",
    endDate: "2026-08-16",
    countryId: 2,
    cityId: 2,
    participantCount: 4,
    permission: "READ_WRITE",
    updatedAt: "2026-07-27T00:00:00Z",
  },
  {
    travelId: "preview-jeju",
    title: "제주 힐링 여행",
    startDate: "2026-09-10",
    endDate: "2026-09-13",
    countryId: 2,
    cityId: 3,
    participantCount: 2,
    permission: "OWNER",
    updatedAt: "2026-07-27T00:00:00Z",
  },
];

function formatDateRange(startDate: string, endDate: string) {
  const [startY, startM, startD] = startDate.split("-");
  const [, endM, endD] = endDate.split("-");
  return `${startY}.${startM}.${startD} - ${endM}.${endD}`;
}

function countDays(startDate: string, endDate: string) {
  const start = new Date(startDate);
  const end = new Date(endDate);
  return Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
}

function toTripListItem(travel: TravelSummary, index: number): TripListItem {
  return {
    id: travel.travelId,
    title: travel.title,
    dates: formatDateRange(travel.startDate, travel.endDate),
    days: countDays(travel.startDate, travel.endDate),
    thumbnailSrc: PREVIEW_THUMBNAILS[index % PREVIEW_THUMBNAILS.length],
  };
}

export default function TripsPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [tab, setTab] = React.useState<ListTab>("mine");
  // query/searchScope는 실제 조회에 쓰이는 "확정된" 값이고, queryDraft/searchScopeDraft는 입력
  // 중인 값이다 — 타이핑할 때마다, 혹은 스코프 드롭다운만 바꿔도 매번 서버로 요청이 나가는 걸 막기
  // 위해 검색창에서 Enter를 눌러야 확정값에 반영되고 그때 비로소 재조회가 일어난다.
  const [query, setQuery] = React.useState("");
  const [searchScope, setSearchScope] = React.useState<TravelSearchScope>("ALL");
  const [queryDraft, setQueryDraft] = React.useState("");
  const [searchScopeDraft, setSearchScopeDraft] = React.useState<TravelSearchScope>("ALL");
  const [travels, setTravels] = React.useState<TravelSummary[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [completedRequestKey, setCompletedRequestKey] =
    React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [showNewTripModal, setShowNewTripModal] = React.useState(false);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [isPreview, setIsPreview] = React.useState(false);
  const [isPreviewLoading, setIsPreviewLoading] = React.useState(false);

  const sentinelRef = React.useRef<HTMLDivElement>(null);

  const requestKey = `${accessToken ?? ""}:${query}:${searchScope}:${refreshKey}`;
  const isLoading = isPreview
    ? isPreviewLoading
    : completedRequestKey !== requestKey;

  React.useEffect(() => {
    const previewRequested =
      process.env.NODE_ENV === "development" &&
      new URLSearchParams(window.location.search).get("preview") === "1";

    if (previewRequested) {
      const keepLoading =
        new URLSearchParams(window.location.search).get("loading") === "1";

      const startTimer = window.setTimeout(() => {
        setIsPreview(true);
        setIsPreviewLoading(true);
        setTravels(PREVIEW_TRAVELS);
      }, 0);

      const finishTimer = keepLoading
        ? undefined
        : window.setTimeout(() => setIsPreviewLoading(false), 1_300);

      return () => {
        window.clearTimeout(startTimer);
        if (finishTimer) window.clearTimeout(finishTimer);
      };
    }

    if (!isInitializing && !isLoggedIn) router.replace("/");
  }, [isInitializing, isLoggedIn, router]);

  // 검색어 또는 refreshKey가 바뀌면 첫 페이지부터 새로 조회한다.
  React.useEffect(() => {
    if (!accessToken) return;

    let isCurrentRequest = true;


    fetchTravels(accessToken, {
      keyword: query.trim() || undefined,
      searchScope,
      page: 0,
      size: PAGE_SIZE,
    })
      .then((res) => {
        if (!isCurrentRequest) return;

        setTravels(res.content);
        setPage(0);
        setIsLast(res.isLast);
        setError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;

        setError("여행일정을 불러오지 못했습니다.");
        setIsLast(true);
      })
      .finally(() => {
        if (isCurrentRequest) {
          setCompletedRequestKey(requestKey);
        }
      });

    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, query, searchScope, requestKey]);

  const loadMore = React.useCallback(() => {
    if (!accessToken || isLast || loadingMore || error) return;

    const nextPage = page + 1;
    setLoadingMore(true);

    fetchTravels(accessToken, {
      keyword: query.trim() || undefined,
      searchScope,
      page: nextPage,
      size: PAGE_SIZE,
    })
      .then((res) => {
        setTravels((prev) => [...prev, ...res.content]);
        setPage(nextPage);
        setIsLast(res.isLast);
      })
      .catch(() => setIsLast(true))
      .finally(() => setLoadingMore(false));
  }, [accessToken, query, searchScope, page, isLast, loadingMore, error]);

  function commitSearch() {
    setError(null);
    setQuery(queryDraft);
    setSearchScope(searchScopeDraft);
  }

  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") commitSearch();
  }

  // 리스트 하단의 sentinel이 화면에 보이면 다음 페이지를 불러온다.
  React.useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) loadMore();
    });

    observer.observe(el);

    return () => observer.disconnect();
  }, [loadMore]);

  if (
    (!isPreview && (isInitializing || !isLoggedIn)) ||
    (isPreview && isPreviewLoading)
  ) {
    return <TripsPageSkeleton />;
  }

  const filtered = travels.filter((travel) => {
    const matchesTab =
      tab === "mine"
        ? travel.permission === "OWNER"
        : travel.permission !== "OWNER";

    const matchesQuery =
      !isPreview ||
      query.trim() === "" ||
      travel.title.toLowerCase().includes(query.trim().toLowerCase());

    return matchesTab && matchesQuery;
  });

  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">여행일정</h1>}
      actions={
        <Button onClick={() => setShowNewTripModal(true)}>
          + 새 여행 만들기
        </Button>
      }
    >
      <div className="mb-4 flex gap-2">
        <Select
          value={searchScopeDraft}
          onValueChange={(v) => setSearchScopeDraft(v as TravelSearchScope)}
        >
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
          placeholder="일정 검색 (Enter로 검색)"
          value={queryDraft}
          onChange={(e) => setQueryDraft(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          containerClassName="flex-1"
        />
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as ListTab)}
        className="mb-5 w-fit"
      >
        <TabsList>
          <TabsTrigger value="mine">내 일정</TabsTrigger>
          <TabsTrigger value="shared">공유받은 일정</TabsTrigger>
        </TabsList>
      </Tabs>

      {error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 py-10 text-center"
        >
          <p className="text-sm text-destructive">{error}</p>

          <Button
            variant="outline"
            onClick={() => {
              setError(null);
              setRefreshKey((key) => key + 1);
            }}
          >
            다시 시도
          </Button>
        </div>
      ) : (
        <TripList
          trips={filtered.map((t, index) => ({
            ...toTripListItem(t, index),
            onClick: () =>
              router.push(
                `/trips/detail?id=${encodeURIComponent(t.travelId)}`,
              ),
          }))}
          isLoading={isLoading}
          isLoadingMore={loadingMore}
          emptyMessage={
            tab === "mine"
              ? "아직 만든 여행일정이 없어요."
              : "공유받은 여행일정이 없어요."
          }
        />
      )}

      {!error && <div ref={sentinelRef} className="h-px" />}

      <NewTripModal
        open={showNewTripModal}
        onOpenChange={setShowNewTripModal}
        accessToken={accessToken}
        onCreated={() => setRefreshKey((k) => k + 1)}
      />
    </ListLayout>
  );
}
