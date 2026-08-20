"use client";

import * as React from "react";
import { Pencil, Trash2, GripVertical } from "lucide-react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy, arrayMove } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
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
  /** 드래그로 카드 순서를 바꿨을 때 새 순서(id 배열, 1번째가 방문 1순위)를 알려준다. readOnly면 드래그 자체가 막힌다. */
  onReorderItems?: (orderedIds: string[]) => void;
  className?: string;
}

interface SortableScheduleItemProps {
  id: string;
  order: number;
  placeName: string;
  note?: string;
  isLast: boolean;
  readOnly: boolean;
  onOpen?: () => void;
  onEdit?: () => void;
  onCancel?: () => void;
  onDelete?: () => void;
}

/** dnd-kit의 useSortable을 여기서만 알게 하고, ScheduleItemCard 자체는 순서 변경 로직을 모르는 순수 표시 컴포넌트로 유지한다. */
function SortableScheduleItem({ id, order, placeName, note, isLast, readOnly, onOpen, onEdit, onCancel, onDelete }: SortableScheduleItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id, disabled: readOnly });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style}>
      <ScheduleItemCard
        order={order}
        placeName={placeName}
        note={note}
        isLast={isLast}
        readOnly={readOnly}
        dragHandle={
          !readOnly ? (
            <button
              type="button"
              title="순서 변경"
              className="flex h-[26px] w-[26px] shrink-0 touch-none cursor-grab items-center justify-center text-muted-foreground active:cursor-grabbing"
              {...attributes}
              {...listeners}
            >
              <Icon icon={GripVertical} size="sm" aria-label="순서 변경" />
            </button>
          ) : undefined
        }
        onOpen={onOpen}
        onEdit={onEdit}
        onCancel={onCancel}
        onDelete={onDelete}
      />
    </div>
  );
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
  onReorderItems,
  className,
}: ScheduleBoardProps) {
  // 클릭(오픈/수정)과 드래그를 같은 카드에서 구분하려고 activationConstraint로 최소 이동 거리를 둔다 —
  // 없으면 짧은 클릭도 드래그 시작으로 인식돼서 onOpen 등이 씹힐 수 있다.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    onReorderItems?.(arrayMove(items, oldIndex, newIndex).map((item) => item.id));
  }

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
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            {items.map((item, i) => (
              <SortableScheduleItem
                key={item.id}
                id={item.id}
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
          </SortableContext>
        </DndContext>
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
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-foreground" title={place.name}>
                      {place.name}
                    </div>
                    {place.note && (
                      <div className="mt-0.5 truncate text-xs text-muted-foreground" title={place.note}>
                        {place.note}
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onAssignPlace?.(place.id)}
                      className="flex min-w-0 flex-1 flex-col cursor-pointer text-left"
                    >
                      <div className="truncate text-sm font-semibold text-foreground" title={place.name}>
                        {place.name}
                      </div>
                      {place.note && (
                        <div className="mt-0.5 truncate text-xs text-muted-foreground" title={place.note}>
                          {place.note}
                        </div>
                      )}
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
