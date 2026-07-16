"use client";

import * as React from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import { ScheduleItemCard } from "@/components/organisms/ScheduleItemCard";
import { cn } from "@/lib/utils";

export interface ScheduleDayTab {
  key: string;
  label: string;
}

export interface ScheduleEntry {
  id: string;
  placeName: string;
  note?: string;
}

export interface UnassignedPlace {
  id: string;
  name: string;
}

export interface ScheduleBoardProps {
  days: ScheduleDayTab[];
  activeDay: string;
  onDayChange: (key: string) => void;
  items: ScheduleEntry[];
  unassigned?: UnassignedPlace[];
  onOpenItem?: (id: string) => void;
  onEditItem?: (id: string) => void;
  onCancelItem?: (id: string) => void;
  onDeleteItem?: (id: string) => void;
  onAssignPlace?: (id: string) => void;
  className?: string;
}

function ScheduleBoard({
  days,
  activeDay,
  onDayChange,
  items,
  unassigned = [],
  onOpenItem,
  onEditItem,
  onCancelItem,
  onDeleteItem,
  onAssignPlace,
  className,
}: ScheduleBoardProps) {
  return (
    <div className={cn("flex flex-col gap-5", className)}>
      <Tabs value={activeDay} onValueChange={onDayChange}>
        <TabsList className="flex-wrap">
          {days.map((day) => (
            <TabsTrigger key={day.key} value={day.key}>
              {day.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div>
        {items.map((item, i) => (
          <ScheduleItemCard
            key={item.id}
            order={i + 1}
            placeName={item.placeName}
            note={item.note}
            isLast={i === items.length - 1}
            onOpen={() => onOpenItem?.(item.id)}
            onEdit={() => onEditItem?.(item.id)}
            onCancel={() => onCancelItem?.(item.id)}
            onDelete={() => onDeleteItem?.(item.id)}
          />
        ))}
      </div>

      {unassigned.length > 0 && (
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-tight text-muted-foreground">
            미배정 목적지
          </div>
          <div className="flex flex-wrap gap-2">
            {unassigned.map((place) => (
              <button
                key={place.id}
                type="button"
                onClick={() => onAssignPlace?.(place.id)}
                className="rounded-lg bg-muted px-3 py-1.5 text-sm font-medium text-secondary-foreground hover:bg-border"
              >
                {place.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export { ScheduleBoard };
