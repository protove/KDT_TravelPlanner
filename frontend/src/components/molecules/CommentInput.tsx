"use client";

import * as React from "react";
import { Input } from "@/components/atoms/Input";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export interface CommentInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  className?: string;
}

function CommentInput({ value, onChange, onSubmit, className }: CommentInputProps) {
  return (
    <form
      className={cn("flex gap-2", className)}
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit();
      }}
    >
      <Input
        placeholder="댓글을 남겨보세요"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1"
      />
      <Button type="submit" size="sm">
        등록
      </Button>
    </form>
  );
}

export { CommentInput };
