"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface MyPageTab {
  key: string;
  label: string;
}

export interface MyPageLayoutProps {
  header?: React.ReactNode;
  tabs: MyPageTab[];
  activeTab: string;
  onTabChange: (key: string) => void;
  children: React.ReactNode;
  className?: string;
}

function MyPageLayout({ header, tabs, activeTab, onTabChange, children, className }: MyPageLayoutProps) {
  const navRef = React.useRef<HTMLElement>(null);
  const [canScrollRight, setCanScrollRight] = React.useState(false);

  const updateScrollHint = React.useCallback(() => {
    const el = navRef.current;
    if (!el) return;
    setCanScrollRight(el.scrollWidth - el.scrollLeft - el.clientWidth > 4);
  }, []);

  React.useEffect(() => {
    updateScrollHint();
    const el = navRef.current;
    if (!el) return;

    el.addEventListener("scroll", updateScrollHint, { passive: true });
    window.addEventListener("resize", updateScrollHint);
    return () => {
      el.removeEventListener("scroll", updateScrollHint);
      window.removeEventListener("resize", updateScrollHint);
    };
  }, [updateScrollHint, tabs]);

  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-4 py-6 md:flex-row md:gap-8 md:px-6 md:py-8">
        {/* 탭 내비게이션 반응형 정책: front.md §6.
            md 이상: 좌측 세로 사이드바(고정폭 180px) 유지.
            md 미만: 동일 마크업을 상단 가로 스크롤 탭바로 전환하고,
            실제로 넘칠 때만 오른쪽 페이드+화살표 힌트를 보여준다. */}
        <div className="relative shrink-0 md:w-[180px]">
          <nav
            ref={navRef}
            aria-label="마이페이지 메뉴"
            className="flex gap-1 overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] md:flex-col md:overflow-visible [&::-webkit-scrollbar]:hidden"
          >
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => onTabChange(tab.key)}
                aria-current={tab.key === activeTab}
                className={cn(
                  "shrink-0 cursor-pointer whitespace-nowrap rounded-lg px-3 py-2 text-left text-sm font-medium",
                  tab.key === activeTab
                    ? "bg-muted text-foreground"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          {canScrollRight && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 right-0 flex w-8 items-center justify-end bg-gradient-to-r from-transparent to-background md:hidden"
            >
              <Icon icon={ChevronRight} size="sm" className="text-muted-foreground" />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">{children}</div>
      </main>
    </div>
  );
}

export { MyPageLayout };
