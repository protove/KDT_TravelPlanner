"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface DateRange {
  start: Date;
  end: Date;
}

export interface CalendarPopoverProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  onApply: () => void;
  className?: string;
}

const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"];

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function isWithinRange(day: Date, start: Date, end: Date) {
  const t = day.getTime();
  return t >= new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime() &&
    t <= new Date(end.getFullYear(), end.getMonth(), end.getDate()).getTime();
}

function CalendarPopover({ value, onChange, onApply, className }: CalendarPopoverProps) {
  const [viewMonth, setViewMonth] = React.useState(() => new Date(value.start.getFullYear(), value.start.getMonth(), 1));
  const [pendingStart, setPendingStart] = React.useState<Date | null>(null);

  const year = viewMonth.getFullYear();
  const month = viewMonth.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const days: (Date | null)[] = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => new Date(year, month, i + 1)),
  ];

  function handleSelectDay(day: Date) {
    if (!pendingStart) {
      setPendingStart(day);
      onChange({ start: day, end: day });
      return;
    }
    const start = pendingStart < day ? pendingStart : day;
    const end = pendingStart < day ? day : pendingStart;
    onChange({ start, end });
    setPendingStart(null);
  }

  return (
    <div className={cn("w-[300px] rounded-xl bg-popover p-4 shadow-dialog", className)}>
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setViewMonth(new Date(year, month - 1, 1))}
          className="text-muted-foreground"
        >
          <Icon icon={ChevronLeft} size="sm" aria-label="이전 달" />
        </button>
        <div className="text-sm font-bold text-foreground">{year}년 {month + 1}월</div>
        <button
          type="button"
          onClick={() => setViewMonth(new Date(year, month + 1, 1))}
          className="text-muted-foreground"
        >
          <Icon icon={ChevronRight} size="sm" aria-label="다음 달" />
        </button>
      </div>

      <div className="mb-1 grid grid-cols-7 gap-1">
        {WEEKDAY_LABELS.map((w) => (
          <div key={w} className="text-center text-xs font-semibold text-muted-foreground">
            {w}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {days.map((day, i) =>
          day ? (
            <button
              key={i}
              type="button"
              onClick={() => handleSelectDay(day)}
              className={cn(
                "flex h-6 items-center justify-center rounded text-[11px]",
                isSameDay(day, value.start) || isSameDay(day, value.end) || isWithinRange(day, value.start, value.end)
                  ? "bg-primary font-bold text-primary-foreground"
                  : "text-foreground hover:bg-muted"
              )}
            >
              {day.getDate()}
            </button>
          ) : (
            <div key={i} />
          )
        )}
      </div>

      <Button className="mt-3 w-full" onClick={onApply}>
        적용
      </Button>
    </div>
  );
}

export { CalendarPopover };
