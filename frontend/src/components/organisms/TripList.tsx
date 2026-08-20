import * as React from "react";
import {
  TripCard,
  TripCardSkeleton,
  type TripCardProps,
} from "@/components/organisms/TripCard";
import { cn } from "@/lib/utils";

export interface TripListItem extends Omit<TripCardProps, "className"> {
  id: string;
}

export interface TripListProps {
  trips: TripListItem[];
  isLoading?: boolean;
  isLoadingMore?: boolean;
  loadingCount?: number;
  emptyMessage?: string;
  className?: string;
}

const gridClassName = "grid gap-4";
const gridStyle = {
  gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 260px), 1fr))",
};

function TripList({
  trips,
  isLoading = false,
  isLoadingMore = false,
  loadingCount = 3,
  emptyMessage = "아직 등록된 여행일정이 없어요.",
  className,
}: TripListProps) {
  if (isLoading) {
    return (
      <div
        role="status"
        aria-label="여행일정을 불러오는 중"
        className={cn(gridClassName, className)}
        style={gridStyle}
      >
        {Array.from({ length: loadingCount }, (_, index) => (
          <TripCardSkeleton key={index} />
        ))}
      </div>
    );
  }

  if (trips.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div
      className={cn(gridClassName, className)}
      style={gridStyle}
    >
      {trips.map(({ id, ...trip }) => (
        <TripCard key={id} {...trip} />
      ))}
      {isLoadingMore && <TripCardSkeleton />}
    </div>
  );
}

export { TripList };
