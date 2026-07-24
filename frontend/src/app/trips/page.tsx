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
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { fetchTravels, type TravelSummary } from "@/lib/api/travel";
import type { TripListItem } from "@/components/organisms/TripList";

type ListTab = "mine" | "shared";

const PAGE_SIZE = 20;

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

function toTripListItem(travel: TravelSummary): TripListItem {
  return {
    id: travel.travelId,
    title: travel.title,
    dates: formatDateRange(travel.startDate, travel.endDate),
    days: countDays(travel.startDate, travel.endDate),
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
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [showNewTripModal, setShowNewTripModal] = React.useState(false);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const sentinelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!isInitializing && !isLoggedIn) router.replace("/landing");
  }, [isInitializing, isLoggedIn, router]);

  // 검색어가 바뀌면 첫 페이지부터 새로 조회한다.
  React.useEffect(() => {
    if (!accessToken) return;
    fetchTravels(accessToken, { keyword: query.trim() || undefined, page: 0, size: PAGE_SIZE })
      .then((res) => {
        setTravels(res.content);
        setPage(0);
        setIsLast(res.isLast);
      })
      .catch(() => {
        setTravels([]);
        setIsLast(true);
      });
  }, [accessToken, query, refreshKey]);

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

  if (isInitializing || !isLoggedIn) return null;

  const filtered = travels.filter((t) => (tab === "mine" ? t.permission === "OWNER" : t.permission !== "OWNER"));

  return (
    <ListLayout
      header={
        <AppHeader
          loggedIn
          userInitial={user?.initial}
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
        trips={filtered.map((t) => ({ ...toTripListItem(t), onClick: () => router.push(`/trips/${t.travelId}`) }))}
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
