import * as React from "react";
import { TripCard, type TripCardProps } from "@/components/organisms/TripCard";
import { cn } from "@/lib/utils";

export interface TripListItem extends Omit<TripCardProps, "className"> {
  id: string;
}

export interface TripListProps {
  trips: TripListItem[];
  emptyMessage?: string;
  className?: string;
}

function TripList({ trips, emptyMessage = "아직 등록된 여행일정이 없어요.", className }: TripListProps) {
  if (trips.length === 0) {
    return <div className="py-16 text-center text-sm text-muted-foreground">{emptyMessage}</div>;
  }

  return (
    <div
      className={cn("grid gap-4", className)}
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}
    >
      {trips.map(({ id, ...trip }) => (
        <TripCard key={id} {...trip} />
      ))}
    </div>
  );
}

export { TripList };
