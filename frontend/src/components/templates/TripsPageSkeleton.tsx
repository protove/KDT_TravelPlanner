import { Skeleton } from "@/components/atoms/Skeleton";
import { TripCardSkeleton } from "@/components/organisms/TripCard";
import { cn } from "@/lib/utils";

export interface TripsPageSkeletonProps {
  cardCount?: number;
  className?: string;
}

function TripsPageSkeleton({
  cardCount = 3,
  className,
}: TripsPageSkeletonProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="여행일정 페이지를 불러오는 중"
      className={cn("flex min-h-screen flex-col bg-background", className)}
    >
      <header className="flex w-full items-center justify-between border-b border-border bg-background px-7 py-3">
        <div className="flex items-center gap-2.5" aria-hidden="true">
          <span className="flex h-[30px] w-[30px] items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
            T
          </span>
          <span className="text-base font-bold text-foreground">TripPlanner</span>
        </div>
        <div className="flex items-center gap-4" aria-hidden="true">
          <Skeleton className="h-[34px] w-[34px] rounded-md" />
          <Skeleton className="h-8 w-8 rounded-full" />
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        <div className="mb-6 flex items-center justify-between gap-3" aria-hidden="true">
          <Skeleton className="h-8 w-28" />
          <Skeleton className="h-9 w-36" />
        </div>

        <div className="mb-4" aria-hidden="true">
          <Skeleton className="h-9 w-full" />
        </div>

        <div className="mb-5 flex w-fit gap-1 rounded-lg bg-muted p-1" aria-hidden="true">
          <Skeleton className="h-7 w-20 bg-card" />
          <Skeleton className="h-7 w-28" />
        </div>

        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          }}
          aria-hidden="true"
        >
          {Array.from({ length: cardCount }, (_, index) => (
            <TripCardSkeleton key={index} />
          ))}
        </div>
      </main>

      <span className="sr-only">여행일정 화면을 준비하고 있어요.</span>
    </div>
  );
}

export { TripsPageSkeleton };
