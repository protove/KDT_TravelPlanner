import * as React from "react";
import { Pencil } from "lucide-react";
import { Icon } from "@/components/atoms/Icon";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { cn } from "@/lib/utils";

export interface TripDetailHeaderProps {
  title: string;
  start: Date;
  end: Date;
  onEditTitle?: () => void;
  onEditDates?: () => void;
  className?: string;
}

function TripDetailHeader({ title, start, end, onEditTitle, onEditDates, className }: TripDetailHeaderProps) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3", className)}>
      <button
        type="button"
        onClick={onEditTitle}
        className="group flex min-w-0 cursor-pointer items-center gap-2"
      >
        <h1 className="truncate text-2xl font-bold text-foreground" title={title}>
          {title}
        </h1>
        <Icon
          icon={Pencil}
          size="sm"
          aria-label="제목 수정"
          className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        />
      </button>

      <button
        type="button"
        onClick={onEditDates}
        className="flex cursor-pointer items-center gap-2 rounded-full bg-card px-3 py-1.5 shadow-card"
      >
        <DateRangeBadge start={start} end={end} />
        <Icon icon={Pencil} size="sm" aria-label="기간 수정" className="text-muted-foreground" />
      </button>
    </div>
  );
}

export { TripDetailHeader };
