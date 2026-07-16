import * as React from "react";
import { cn } from "@/lib/utils";

export interface AuthLayoutProps {
  header?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

function AuthLayout({ header, children, className }: AuthLayoutProps) {
  return (
    <div className={cn("flex min-h-screen flex-col bg-background", className)}>
      {header}
      <main className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm rounded-xl bg-card p-8 shadow-dialog">{children}</div>
      </main>
    </div>
  );
}

export { AuthLayout };
