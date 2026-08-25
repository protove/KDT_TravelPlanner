"use client";

import * as React from "react";
import { Textarea } from "@/components/atoms/Textarea";
import { Button } from "@/components/atoms/Button";
import { clampCommentLines } from "@/lib/utils/clampCommentLines";
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

// form의 암묵적 제출(Enter로 submit)을 아예 쓰지 않는다 — "등록" 버튼을 눌렀을 때만 댓글이
// 올라가야 한다는 요구사항에 따라 <form onSubmit> 대신 버튼 onClick으로만 제출을 트리거한다.
// (참고로 <textarea>는 애초에 Enter로 form submit되지 않지만, 의도를 코드로도 명시해둔다.)
function CommentInput({ value, onChange, onSubmit, submitting = false, maxLength, className }: CommentInputProps) {
  const canSubmit = value.trim().length > 0 && !submitting;

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Textarea
        placeholder="댓글을 남겨보세요 (최대 50줄)"
        value={value}
        onChange={(e) => onChange(clampCommentLines(e.target.value))}
        disabled={submitting}
        maxLength={maxLength}
        rows={3}
        className="min-h-[80px] resize-y"
      />
      <Button
        type="button"
        size="sm"
        className="self-end"
        disabled={!canSubmit}
        onClick={onSubmit}
      >
        {submitting ? "등록 중..." : "등록"}
      </Button>
    </div>
  );
}

export { CommentInput };
