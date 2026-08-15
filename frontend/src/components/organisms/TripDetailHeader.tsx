"use client";

import * as React from "react";
import { Pencil, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Icon } from "@/components/atoms/Icon";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/atoms/Avatar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { CalendarPopover, type DateRange } from "@/components/organisms/CalendarPopover";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import type { Country, City } from "@/lib/api/location";
import type { TravelMember } from "@/lib/api/members";
import { TITLE_MAX_LENGTH } from "@/lib/validation/text";
import { cn } from "@/lib/utils";

export interface TripDetailHeaderProps {
  onBack: () => void;
  title: string;
  isEditing: boolean;
  titleDraft: string;
  onTitleDraftChange: (value: string) => void;
  /** 제목/기간/설명 등 "정보 수정" 모드 전체를 켤 수 있는지 — 참여 권한에 따라 결정된다. */
  canEdit: boolean;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  saveError?: string | null;
  isOwner: boolean;
  onDeleteClick: () => void;
  members: TravelMember[];
  onInviteClick: () => void;
  onManageClick: () => void;
  onLeaveClick: () => void;
  countries: Country[];
  selectedCountryId: number | null;
  onCountryChange: (value: string) => void;
  cities: City[];
  selectedCityId: number | null;
  onCityChange: (value: string) => void;
  selectedCountryName: string;
  selectedCityName: string;
  dateRange: DateRange;
  onDateRangeChange: (range: DateRange) => void;
  showCalendar: boolean;
  onToggleCalendar: () => void;
  onApplyCalendar: () => void;
  companion: string;
  onCompanionChange: (value: string) => void;
  companionOptions: readonly string[];
  className?: string;
}

function TripDetailHeader({
  onBack,
  title,
  isEditing,
  titleDraft,
  onTitleDraftChange,
  canEdit,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
  saveError,
  isOwner,
  onDeleteClick,
  members,
  onInviteClick,
  onManageClick,
  onLeaveClick,
  countries,
  selectedCountryId,
  onCountryChange,
  cities,
  selectedCityId,
  onCityChange,
  selectedCountryName,
  selectedCityName,
  dateRange,
  onDateRangeChange,
  showCalendar,
  onToggleCalendar,
  onApplyCalendar,
  companion,
  onCompanionChange,
  companionOptions,
  className,
}: TripDetailHeaderProps) {
  const acceptedMembers = members.filter((m) => m.status === "ACCEPTED");

  return (
    <div className={cn("flex flex-col gap-5", className)}>
      <button
        type="button"
        onClick={onBack}
        className="self-start cursor-pointer text-sm font-bold text-primary"
      >
        ← 여행일정 목록
      </button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            {isEditing ? (
              <Input
                autoFocus
                value={titleDraft}
                maxLength={TITLE_MAX_LENGTH}
                onChange={(e) => onTitleDraftChange(e.target.value)}
                className="h-auto w-auto text-2xl font-bold"
              />
            ) : (
              <h1 className="text-2xl font-bold text-foreground">{title}</h1>
            )}
            {canEdit && (
              <>
                {isEditing ? (
                  <>
                    <button type="button" title="저장" className="cursor-pointer text-primary" onClick={onSaveEdit}>
                      <Icon icon={Check} size="sm" aria-label="저장" />
                    </button>
                    <button type="button" title="취소" className="cursor-pointer text-muted-foreground" onClick={onCancelEdit}>
                      <Icon icon={X} size="sm" aria-label="취소" />
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" title="정보 수정" className="cursor-pointer text-muted-foreground" onClick={onStartEdit}>
                      <Icon icon={Pencil} size="sm" aria-label="정보 수정" />
                    </button>
                    {isOwner && (
                      <button type="button" title="여행일정 삭제" className="cursor-pointer text-destructive" onClick={onDeleteClick}>
                        <Icon icon={Trash2} size="sm" aria-label="여행일정 삭제" />
                      </button>
                    )}
                  </>
                )}
              </>
            )}
          </div>
          {isEditing && (
            <p className="mt-1 text-xs text-muted-foreground">
              {titleDraft.length}/{TITLE_MAX_LENGTH}
            </p>
          )}
          {saveError && <p className="mt-1 text-xs text-destructive">{saveError}</p>}
          <div className="mt-1.5 flex">
            {acceptedMembers.map((m, i) => (
              <Avatar
                key={m.userId}
                className="h-[22px] w-[22px]"
                style={i > 0 ? { marginLeft: "-6px" } : undefined}
              >
                {m.profileImageUrl && <AvatarImage src={m.profileImageUrl} alt={m.nickname ?? ""} />}
                <AvatarFallback className="text-[10px]">{(m.nickname ?? "?").slice(0, 1)}</AvatarFallback>
              </Avatar>
            ))}
          </div>
        </div>

        {isOwner ? (
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={onInviteClick}>
              참여자 초대
            </Button>
            <Button onClick={onManageClick}>참여자 관리</Button>
          </div>
        ) : (
          <Button variant="outline" onClick={onLeaveClick}>
            나가기
          </Button>
        )}
      </div>

      {isEditing ? (
        <div className="relative flex w-fit flex-wrap items-center gap-1 rounded-full bg-card p-1.5 shadow-card">
          <div className="flex items-center gap-1.5 px-2.5 py-1.5">
            <span>📍</span>
            <Select
              value={selectedCountryId != null ? String(selectedCountryId) : undefined}
              onValueChange={onCountryChange}
            >
              <SelectTrigger className="h-auto w-auto gap-1 border-none bg-transparent px-0.5 py-0.5 text-sm font-bold shadow-none">
                <SelectValue placeholder="나라" />
              </SelectTrigger>
              <SelectContent>
                {countries.map((c) => (
                  <SelectItem key={c.countryId} value={String(c.countryId)}>
                    {c.nameKo}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-border-strong">·</span>
            <Select
              value={selectedCityId != null ? String(selectedCityId) : undefined}
              onValueChange={onCityChange}
              disabled={selectedCountryId == null}
            >
              <SelectTrigger className="h-auto w-auto gap-1 border-none bg-transparent px-0.5 py-0.5 text-sm font-bold shadow-none">
                <SelectValue placeholder="도시" />
              </SelectTrigger>
              <SelectContent>
                {cities.map((c) => (
                  <SelectItem key={c.cityId} value={String(c.cityId)}>
                    {c.nameKo}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="h-5 w-px bg-border" />
          <button
            type="button"
            onClick={onToggleCalendar}
            className="flex cursor-pointer items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold text-foreground hover:bg-muted"
          >
            📅 <DateRangeBadge start={dateRange.start} end={dateRange.end} />
          </button>
          <div className="h-5 w-px bg-border" />
          <Select value={companion} onValueChange={onCompanionChange}>
            <SelectTrigger className="h-auto w-auto gap-1.5 border-none px-3 py-1.5 shadow-none">
              <span>👥</span>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {companionOptions.map((opt) => (
                <SelectItem key={opt} value={opt}>
                  {opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {showCalendar && (
            <div className="absolute left-0 top-[calc(100%+8px)] z-20">
              <CalendarPopover value={dateRange} onChange={onDateRangeChange} onApply={onApplyCalendar} />
            </div>
          )}
        </div>
      ) : (
        <div className="flex w-fit flex-wrap items-center gap-1 rounded-full bg-card p-1.5 shadow-card">
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-bold text-foreground">
            📍 {selectedCountryName} · {selectedCityName}
          </div>
          <div className="h-5 w-px bg-border" />
          <div className="flex items-center gap-2 px-3.5 py-2 text-sm font-bold text-foreground">
            📅 <DateRangeBadge start={dateRange.start} end={dateRange.end} />
          </div>
          <div className="h-5 w-px bg-border" />
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-bold text-foreground">
            👥 {companion}
          </div>
        </div>
      )}
    </div>
  );
}

export { TripDetailHeader };
