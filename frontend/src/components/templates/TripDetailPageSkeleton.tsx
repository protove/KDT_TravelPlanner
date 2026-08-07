import { Skeleton } from "@/components/atoms/Skeleton";
import { cn } from "@/lib/utils";

export interface TripDetailPageSkeletonProps {
  itemCount?: number;
  className?: string;
}

/**
 * 여행상세 데이터(fetchTravelDetail) 로딩 중 보여주는 스켈레톤.
 * 헤더는 이제 루트 레이아웃(HeaderLayout)에서 한 번만 렌더링되므로 여기엔 포함하지 않는다.
 */
function TripDetailPageSkeleton({
  itemCount = 3,
  className,
}: TripDetailPageSkeletonProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="여행상세 화면을 불러오는 중"
      className={cn("flex min-h-screen flex-col bg-background", className)}
    >
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8">
        <div className="mb-6 flex flex-col gap-5" aria-hidden="true">
          <Skeleton className="h-5 w-28" />

          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Skeleton className="h-8 w-52" />
              <div className="mt-2 flex">
                {Array.from({ length: 3 }, (_, index) => (
                  <Skeleton
                    key={index}
                    className="h-[22px] w-[22px] rounded-full ring-2 ring-background"
                    style={index > 0 ? { marginLeft: "-6px" } : undefined}
                  />
                ))}
              </div>
            </div>
            <Skeleton className="h-9 w-24 rounded-md" />
          </div>

          <Skeleton className="h-11 w-80 rounded-full" />
        </div>

        <div className="flex flex-col gap-6" aria-hidden="true">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-9 w-full max-w-xs" />
          <Skeleton className="h-[320px] w-full rounded-xl" />

          <div className="flex flex-col gap-2">
            {Array.from({ length: itemCount }, (_, index) => (
              <div key={index} className="flex items-center gap-3 rounded-lg bg-card p-3 shadow-card">
                <Skeleton className="h-6 w-6 shrink-0 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
            ))}
          </div>

          <div>
            <Skeleton className="mb-2 h-4 w-20" />
            <Skeleton className="h-[90px] w-full" />
          </div>
        </div>
      </main>

      <span className="sr-only">여행상세 화면을 준비하고 있어요.</span>
    </div>
  );
}

export { TripDetailPageSkeleton };
