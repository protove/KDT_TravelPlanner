import * as React from "react";
import { Pencil, Trash2, Undo2 } from "lucide-react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface ScheduleItemCardProps {
  order: number;
  placeName: string;
  note?: string;
  isLast?: boolean;
  /** READ_ONLY 권한 등 조회만 가능할 때 수정/취소/삭제 아이콘을 아예 숨긴다. */
  readOnly?: boolean;
  onOpen?: () => void;
  onEdit?: () => void;
  onCancel?: () => void;
  onDelete?: () => void;
  className?: string;
}

function ScheduleItemCard({
  order,
  placeName,
  note,
  isLast = false,
  readOnly = false,
  onOpen,
  onEdit,
  onCancel,
  onDelete,
  className,
}: ScheduleItemCardProps) {
  return (
    <div className={cn("flex gap-3.5", className)}>
      <div className="flex w-[30px] shrink-0 flex-col items-center">
        <div className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
          {order}
        </div>
        {!isLast && <div className="w-0.5 flex-1 bg-border" />}
      </div>

      <div className="mb-3.5 flex flex-1 items-start gap-2.5 rounded-xl bg-card p-3.5 shadow-card">
        <button type="button" onClick={onOpen} className="flex flex-1 cursor-pointer text-left">
          <div className="text-[15px] font-bold text-foreground">{placeName}</div>
          {note ? (
            <div className="mt-1 text-sm text-muted-foreground">{note}</div>
          ) : (
            !readOnly && <div className="mt-1 text-sm text-muted-foreground">+ 할 일 메모 추가</div>
          )}
        </button>
        {!readOnly && (
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              title="수정"
              onClick={onEdit}
              className="flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
            >
              <Icon icon={Pencil} size="sm" aria-label="수정" />
            </button>
            <button
              type="button"
              title="미배정으로 취소"
              onClick={onCancel}
              className="flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
            >
              <Icon icon={Undo2} size="sm" aria-label="미배정으로 취소" />
            </button>
            <button
              type="button"
              title="완전 삭제"
              onClick={onDelete}
              className="flex h-[26px] w-[26px] cursor-pointer items-center justify-center rounded-md text-destructive hover:bg-muted"
            >
              <Icon icon={Trash2} size="sm" aria-label="완전 삭제" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export { ScheduleItemCard };
