"use client";

import * as React from "react";
import { Pencil, Trash2 } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/atoms/Tabs";
import { Icon } from "@/components/atoms/Icon";
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
  note?: string;
}

export interface ScheduleBoardProps {
  days: ScheduleDayTab[];
  activeDay: string;
  onDayChange: (key: string) => void;
  items: ScheduleEntry[];
  unassigned?: UnassignedPlace[];
  /** 날짜 탭과 일정 목록 사이에 끼워 넣는 지도 영역 (초안 순서: 탭 → 지도 → 일정 목록). */
  map?: React.ReactNode;
  /** READ_ONLY 권한 등 조회만 가능할 때 수정/취소/삭제 관련 버튼을 전부 숨긴다. */
  readOnly?: boolean;
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
  map,
  readOnly = false,
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

      {map}

      <div>
        {items.map((item, i) => (
          <ScheduleItemCard
            key={item.id}
            order={i + 1}
            placeName={item.placeName}
            note={item.note}
            isLast={i === items.length - 1}
            readOnly={readOnly}
            onOpen={() => onOpenItem?.(item.id)}
            onEdit={() => onEditItem?.(item.id)}
            onCancel={() => onCancelItem?.(item.id)}
            onDelete={() => onDeleteItem?.(item.id)}
          />
        ))}
      </div>

      {unassigned.length > 0 && (
        <div>
          <div className="mb-2 text-sm font-bold text-foreground">미배정 목록</div>
          <div className="flex flex-col gap-2">
            {unassigned.map((place) => (
              <div
                key={place.id}
                className="flex items-center gap-3 rounded-lg bg-card p-2.5 px-3.5 shadow-card"
              >
                {readOnly ? (
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-foreground">{place.name}</div>
                    {place.note && <div className="mt-0.5 text-xs text-muted-foreground">{place.note}</div>}
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onAssignPlace?.(place.id)}
                      className="flex flex-1 cursor-pointer text-left"
                    >
                      <div className="text-sm font-semibold text-foreground">{place.name}</div>
                      {place.note && <div className="mt-0.5 text-xs text-muted-foreground">{place.note}</div>}
                    </button>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        title="수정"
                        onClick={() => onAssignPlace?.(place.id)}
                        className="flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                      >
                        <Icon icon={Pencil} size="sm" aria-label="수정" />
                      </button>
                      <button
                        type="button"
                        title="완전 삭제"
                        onClick={() => onDeleteItem?.(place.id)}
                        className="flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md text-destructive hover:bg-muted"
                      >
                        <Icon icon={Trash2} size="sm" aria-label="완전 삭제" />
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export { ScheduleBoard };
