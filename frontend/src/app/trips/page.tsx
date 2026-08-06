"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import { AppHeader } from "@/components/organisms/AppHeader";
import { TripList } from "@/components/organisms/TripList";
import { NewTripModal } from "@/components/organisms/NewTripModal";
import { SearchBar } from "@/components/molecules/SearchBar";
import { ListLayout } from "@/components/templates/ListLayout";
import { TripsPageSkeleton } from "@/components/templates/TripsPageSkeleton";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { fetchTravels, type TravelSummary } from "@/lib/api/travel";
import type { TripListItem } from "@/components/organisms/TripList";

type ListTab = "mine" | "shared";

const PAGE_SIZE = 20;
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
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [tab, setTab] = React.useState<ListTab>("mine");
  const [query, setQuery] = React.useState("");
  const [travels, setTravels] = React.useState<TravelSummary[]>([]);
  const [page, setPage] = React.useState(0);
  const [isLast, setIsLast] = React.useState(false);
  const [completedRequestKey, setCompletedRequestKey] = React.useState<string | null>(null);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [showNewTripModal, setShowNewTripModal] = React.useState(false);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [isPreview, setIsPreview] = React.useState(false);
  const [isPreviewLoading, setIsPreviewLoading] = React.useState(false);
  const sentinelRef = React.useRef<HTMLDivElement>(null);
  const requestKey = `${accessToken ?? ""}:${query}:${refreshKey}`;
  const isLoading = isPreview ? isPreviewLoading : completedRequestKey !== requestKey;

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

  // 검색어가 바뀌면 첫 페이지부터 새로 조회한다.
  React.useEffect(() => {
    if (!accessToken) return;
    let isCurrentRequest = true;
    fetchTravels(accessToken, { keyword: query.trim() || undefined, page: 0, size: PAGE_SIZE })
      .then((res) => {
        if (!isCurrentRequest) return;
        setTravels(res.content);
        setPage(0);
        setIsLast(res.isLast);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setTravels([]);
        setIsLast(true);
      })
      .finally(() => {
        if (isCurrentRequest) setCompletedRequestKey(requestKey);
      });
    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, query, requestKey]);

  const loadMore = React.useCallback(() => {
    if (!accessToken || isLast || loadingMore) return;
    const nextPage = page + 1;
    setLoadingMore(true);
    fetchTravels(accessToken, { keyword: query.trim() || undefined, page: nextPage, size: PAGE_SIZE })
      .then((res) => {
        setTravels((prev) => [...prev, ...res.content]);
        setPage(nextPage);
        setIsLast(res.isLast);
      })
      .catch(() => setIsLast(true))
      .finally(() => setLoadingMore(false));
  }, [accessToken, query, page, isLast, loadingMore]);

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
      tab === "mine" ? travel.permission === "OWNER" : travel.permission !== "OWNER";
    const matchesQuery =
      !isPreview ||
      query.trim() === "" ||
      travel.title.toLowerCase().includes(query.trim().toLowerCase());
    return matchesTab && matchesQuery;
  });

  return (
    <ListLayout
      header={
        <AppHeader
          loggedIn
          userInitial={user?.initial ?? "여"}
          avatarColor={user?.avatarColor}
          onLogoClick={() => router.push("/trips")}
          onProfileClick={() => router.push("/mypage")}
          onNotificationClick={() => router.push("/notifications")}
        />
      }
      title={<h1 className="text-2xl font-bold text-foreground">여행일정</h1>}
      actions={<Button onClick={() => setShowNewTripModal(true)}>+ 새 여행 만들기</Button>}
    >
      <SearchBar
        placeholder="일정 검색"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        containerClassName="mb-4"
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as ListTab)} className="mb-5 w-fit">
        <TabsList>
          <TabsTrigger value="mine">내 일정</TabsTrigger>
          <TabsTrigger value="shared">공유받은 일정</TabsTrigger>
        </TabsList>
      </Tabs>

      <TripList
        trips={filtered.map((t, index) => ({
          ...toTripListItem(t, index),
          onClick: () => router.push(`/trips/detail?id=${encodeURIComponent(t.travelId)}`),
        }))}
        isLoading={isLoading}
        isLoadingMore={loadingMore}
        emptyMessage={tab === "mine" ? "아직 만든 여행일정이 없어요." : "공유받은 여행일정이 없어요."}
      />
      <div ref={sentinelRef} className="h-px" />

      <NewTripModal
        open={showNewTripModal}
        onOpenChange={setShowNewTripModal}
        accessToken={accessToken}
        onCreated={() => setRefreshKey((k) => k + 1)}
      />
    </ListLayout>
  );
}
