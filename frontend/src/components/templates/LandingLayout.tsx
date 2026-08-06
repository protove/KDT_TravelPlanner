import * as React from "react";
import { cn } from "@/lib/utils";

export interface LandingLayoutProps {
  header?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

function LandingLayout({ header, children, className }: LandingLayoutProps) {
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center">
        {children}
      </main>
    </div>
  );
}

export { LandingLayout };
