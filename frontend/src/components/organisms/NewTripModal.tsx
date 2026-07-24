"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/atoms/Dialog";
import { CalendarPopover, type DateRange } from "@/components/organisms/CalendarPopover";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { createTravel } from "@/lib/api/travel";

export interface NewTripModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accessToken: string | null;
  onCreated: () => void;
}

function toIsoDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function NewTripModal({ open, onOpenChange, accessToken, onCreated }: NewTripModalProps) {
  const [title, setTitle] = React.useState("");
  const [range, setRange] = React.useState<DateRange>(() => {
    const today = new Date();
    return { start: today, end: today };
  });
  const [showCalendar, setShowCalendar] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit() {
    if (!accessToken || !title.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await createTravel(accessToken, {
        title: title.trim(),
        startDate: toIsoDate(range.start),
        endDate: toIsoDate(range.end),
      });
      setTitle("");
      onOpenChange(false);
      onCreated();
    } catch {
      setError("여행 생성에 실패했어요.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[360px]">
        <DialogHeader>
          <DialogTitle>새 여행 만들기</DialogTitle>
        </DialogHeader>

        <Input placeholder="여행 제목" value={title} onChange={(e) => setTitle(e.target.value)} />

        <div className="relative w-fit">
          <button
            type="button"
            onClick={() => setShowCalendar((v) => !v)}
            className="flex items-center gap-2 rounded-full bg-muted px-3.5 py-2 text-sm font-bold text-foreground"
          >
            📅 <DateRangeBadge start={range.start} end={range.end} />
          </button>
          {showCalendar && (
            <div className="absolute left-0 top-[calc(100%+8px)] z-20">
              <CalendarPopover value={range} onChange={setRange} onApply={() => setShowCalendar(false)} />
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            닫기
          </Button>
          <Button onClick={handleSubmit} disabled={!title.trim() || submitting}>
            {submitting ? "만드는 중..." : "만들기"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export { NewTripModal };
