"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/atoms/Dialog";
import { cn } from "@/lib/utils";

export interface PlaceDateChip {
  label: string;
  selected: boolean;
}

export interface PlaceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "add" | "edit";
  title: string;
  name: string;
  onNameChange: (value: string) => void;
  note: string;
  onNoteChange: (value: string) => void;
  dateChips?: PlaceDateChip[];
  onSelectDateChip?: (index: number) => void;
  onSave: () => void;
}

function PlaceModal({
  open,
  onOpenChange,
  mode,
  title,
  name,
  onNameChange,
  note,
  onNoteChange,
  dateChips,
  onSelectDateChip,
  onSave,
}: PlaceModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[360px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {mode === "add" && (
          <Input placeholder="장소 이름" value={name} onChange={(e) => onNameChange(e.target.value)} />
        )}

        <Textarea
          placeholder="이 장소에서 뭘 할지 적어보세요"
          value={note}
          onChange={(e) => onNoteChange(e.target.value)}
          className="h-[70px] resize-none"
        />

        {mode === "edit" && dateChips && dateChips.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs text-muted-foreground">날짜 배정</div>
            <div className="flex flex-wrap gap-1.5">
              {dateChips.map((chip, i) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={() => onSelectDateChip?.(i)}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs font-semibold",
                    chip.selected ? "bg-primary text-primary-foreground" : "bg-muted text-secondary-foreground"
                  )}
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            닫기
          </Button>
          <Button onClick={onSave}>저장</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { PlaceModal };
