"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/atoms/Dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { cn } from "@/lib/utils";

export const TIMELINE_CATEGORY_OPTIONS = ["관광지", "음식", "숙소", "교통", "기타"] as const;
export type TimelineCategoryOption = (typeof TIMELINE_CATEGORY_OPTIONS)[number];

export interface PlaceDateChip {
  label: string;
  selected: boolean;
}

export interface PlaceSearchResultOption {
  placeId: string;
  name: string;
  latitude: number;
  longitude: number;
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
  category: TimelineCategoryOption;
  onCategoryChange: (value: TimelineCategoryOption) => void;
  foodSubcategory?: string;
  onFoodSubcategoryChange?: (value: string) => void;
  /** add 모드에서만 쓰는 장소 검색(Google Places). 검색으로 고르면 name/googlePlaceId가 채워진다. */
  placeQuery?: string;
  onPlaceQueryChange?: (value: string) => void;
  placeResults?: PlaceSearchResultOption[];
  onSelectPlaceResult?: (result: PlaceSearchResultOption) => void;
  dateChips?: PlaceDateChip[];
  onSelectDateChip?: (index: number) => void;
  onSave: () => void;
  /** READ_ONLY 권한 등 조회만 가능할 때 모든 입력을 비활성화하고 저장 버튼을 숨긴다. */
  readOnly?: boolean;
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
  category,
  onCategoryChange,
  foodSubcategory = "",
  onFoodSubcategoryChange,
  placeQuery,
  onPlaceQueryChange,
  placeResults = [],
  onSelectPlaceResult,
  dateChips,
  onSelectDateChip,
  onSave,
  readOnly = false,
}: PlaceModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[360px]">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        {mode === "add" && onPlaceQueryChange && (
          <div>
            <Input
              placeholder="장소 검색 (선택 사항)"
              value={placeQuery ?? ""}
              onChange={(e) => onPlaceQueryChange(e.target.value)}
            />
            {placeResults.length > 0 && (
              <div className="mt-1.5 flex max-h-48 flex-col gap-1 overflow-y-auto rounded-lg border border-border bg-popover p-1.5 shadow-dialog">
                {placeResults.map((result) => (
                  <button
                    key={result.placeId}
                    type="button"
                    onClick={() => onSelectPlaceResult?.(result)}
                    className="cursor-pointer rounded-md px-2.5 py-1.5 text-left text-sm text-foreground hover:bg-muted"
                  >
                    {result.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {mode === "add" && (
          <Input
            placeholder="장소 이름"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            disabled={readOnly}
          />
        )}

        <Select
          value={category}
          onValueChange={(v) => onCategoryChange(v as TimelineCategoryOption)}
          disabled={readOnly}
        >
          <SelectTrigger>
            <SelectValue placeholder="카테고리" />
          </SelectTrigger>
          <SelectContent>
            {TIMELINE_CATEGORY_OPTIONS.map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {category === "음식" && onFoodSubcategoryChange && (
          <Input
            placeholder="음식 종류 (예: 라멘, 스시)"
            value={foodSubcategory}
            onChange={(e) => onFoodSubcategoryChange(e.target.value)}
            disabled={readOnly}
          />
        )}

        <Textarea
          placeholder="이 장소에서 뭘 할지 적어보세요"
          value={note}
          onChange={(e) => onNoteChange(e.target.value)}
          className="h-[70px] resize-none"
          disabled={readOnly}
        />

        {mode === "edit" && dateChips && dateChips.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs text-muted-foreground">날짜 배정</div>
            <div className="flex flex-wrap gap-1.5">
              {dateChips.map((chip, i) => (
                <button
                  key={chip.label}
                  type="button"
                  disabled={readOnly}
                  onClick={() => onSelectDateChip?.(i)}
                  className={cn(
                    "cursor-pointer rounded-md px-2.5 py-1 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50",
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
          {!readOnly && <Button onClick={onSave}>저장</Button>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { PlaceModal };
