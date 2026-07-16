import * as React from "react";
import { cn } from "@/lib/utils";

export interface ListLayoutProps {
  header?: React.ReactNode;
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

function ListLayout({ header, title, actions, children, className }: ListLayoutProps) {
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">
        {(title || actions) && (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            {title}
            {actions}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}

export { ListLayout };
