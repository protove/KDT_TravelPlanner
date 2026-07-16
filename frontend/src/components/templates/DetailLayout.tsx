import * as React from "react";
import { cn } from "@/lib/utils";

export interface DetailLayoutProps {
  header?: React.ReactNode;
  detailHeader?: React.ReactNode;
  schedule: React.ReactNode;
  map: React.ReactNode;
  className?: string;
}

/**
 * 2-pane: 일정(schedule) + 지도(map). 미디어쿼리 대신 flex-wrap으로 좁아지면
 * 지도 pane이 아래로 떨어지는 유동형 레이아웃 (디자인.md §7).
 */
function DetailLayout({ header, detailHeader, schedule, map, className }: DetailLayoutProps) {
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        {detailHeader && <div className="mb-6">{detailHeader}</div>}
        <div className="flex flex-wrap gap-6">
          <div className="min-w-[320px] flex-1 basis-[380px]">{schedule}</div>
          <div className="min-w-[320px] flex-[2] basis-[480px]">{map}</div>
        </div>
      </main>
    </div>
  );
}

export { DetailLayout };
