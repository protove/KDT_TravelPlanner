"use client";

import * as React from "react";
import { Input } from "@/components/atoms/Input";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export interface CommentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** 등록 요청이 진행 중이면 입력/버튼을 비활성화하고 버튼 라벨을 바꾼다. */
  submitting?: boolean;
  maxLength?: number;
  className?: string;
}

function CommentInput({ value, onChange, onSubmit, submitting = false, maxLength, className }: CommentInputProps) {
  const canSubmit = value.trim().length > 0 && !submitting;

  return (
    <form
      className={cn("flex gap-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) onSubmit();
      }}
    >
      <Input
        placeholder="댓글을 남겨보세요"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={submitting}
        maxLength={maxLength}
        className="flex-1"
      />
      <Button type="submit" size="sm" disabled={!canSubmit}>
        {submitting ? "등록 중..." : "등록"}
      </Button>
    </form>
  );
}

export { CommentInput };
