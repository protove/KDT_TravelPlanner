"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/Select";
import { SEARCH_PERIOD_OPTIONS, type SearchPeriodPreset } from "@/lib/utils/searchPeriod";
import { cn } from "@/lib/utils";

export interface SearchPeriodSelectProps {
  value: SearchPeriodPreset;
  onValueChange: (value: SearchPeriodPreset) => void;
  className?: string;
}

/**
 * 검색 결과를 "전체 기간"으로 무제한 조회하지 않도록 커뮤니티/여행일정/마이페이지 검색 전반에서
 * 공유하는 기간 선택 드롭다운. 카테고리/정렬처럼 선택 즉시 반영된다(검색어처럼 Enter 대기 안 함).
 */
function SearchPeriodSelect({ value, onValueChange, className }: SearchPeriodSelectProps) {
  return (
    <Select value={value} onValueChange={(v) => onValueChange(v as SearchPeriodPreset)}>
      <SelectTrigger className={cn("w-28 shrink-0", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {SEARCH_PERIOD_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export { SearchPeriodSelect };
