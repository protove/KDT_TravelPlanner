"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import { AppHeader } from "@/components/organisms/AppHeader";
import { TripList } from "@/components/organisms/TripList";
import { SearchBar } from "@/components/molecules/SearchBar";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useTripStore } from "@/lib/stores/useTripStore";

type ListTab = "mine" | "shared";

export default function TripsPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const user = useAuthStore((s) => s.user);
  const trips = useTripStore((s) => s.trips);

  const [tab, setTab] = React.useState<ListTab>("mine");
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (!isInitializing && !isLoggedIn) router.replace("/landing");
  }, [isInitializing, isLoggedIn, router]);

  if (isInitializing || !isLoggedIn) return null;

  const filtered = trips
    .filter((trip) => (tab === "mine" ? trip.mine : !trip.mine))
    .filter((trip) => trip.title.includes(query.trim()));

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
      actions={<Button onClick={() => router.push("/trips/1")}>+ 새 여행 만들기</Button>}
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
        trips={filtered.map((trip) => ({ ...trip, onClick: () => router.push(`/trips/${trip.id}`) }))}
        emptyMessage={tab === "mine" ? "아직 만든 여행일정이 없어요." : "공유받은 여행일정이 없어요."}
      />
    </ListLayout>
  );
}
