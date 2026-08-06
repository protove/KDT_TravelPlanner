import * as React from "react";
import { cn } from "@/lib/utils";

export interface DetailLayoutProps {
  header?: React.ReactNode;
  detailHeader?: React.ReactNode;
  schedule: React.ReactNode;
  className?: string;
}

/**
 * 1단 세로 레이아웃: 헤더 → 일정(지도는 ScheduleBoard의 map 슬롯으로 탭과 목록 사이에 인라인 배치).
 * 초안(TripPlanner Standalone.html)의 화면 순서를 따른다 — 지도를 별도 사이드 패널로 분리하지 않는다.
 */
function DetailLayout({ header, detailHeader, schedule, className }: DetailLayoutProps) {
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8">
        {detailHeader && <div className="mb-6">{detailHeader}</div>}
        {schedule}
      </main>
    </div>
  );
}

export { DetailLayout };
