import * as React from "react";
import { Badge } from "@/components/atoms/Badge";
import { cn } from "@/lib/utils";

export interface DateRangeBadgeProps {
  start: Date;
  end: Date;
  className?: string;
}

function formatMonthDay(date: Date) {
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function DateRangeBadge({ start, end, className }: DateRangeBadgeProps) {
  const nights = Math.round((end.getTime() - start.getTime()) / 86_400_000);
  const days = nights + 1;

  return (
    <div className={cn("inline-flex items-center gap-1.5 text-sm font-semibold text-foreground", className)}>
      <span>
        {formatMonthDay(start)} - {formatMonthDay(end)}
      </span>
      {nights > 0 && <Badge variant="accent">{nights}박{days}일</Badge>}
    </div>
  );
}

export { DateRangeBadge };
