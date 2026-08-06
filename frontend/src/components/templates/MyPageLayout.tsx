import * as React from "react";
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
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="mx-auto flex w-full max-w-5xl flex-1 gap-8 px-6 py-8">
        {/* 사이드바 탭은 폭이 좁아져도 항상 flex-col 유지 (디자인.md §7 — row로 바꾸면 레이아웃이 깨짐) */}
        <nav className="flex w-[180px] shrink-0 flex-col gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => onTabChange(tab.key)}
              aria-current={tab.key === activeTab}
              className={cn(
                "cursor-pointer rounded-lg px-3 py-2 text-left text-sm font-medium",
                tab.key === activeTab
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </main>
    </div>
  );
}

export { MyPageLayout };
