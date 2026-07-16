"use client";

import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export type Permission = "read" | "write";

export interface PermissionSelectProps {
  value: Permission;
  onChange?: (value: Permission) => void;
  disabled?: boolean;
  className?: string;
}

function PermissionSelect({ value, onChange, disabled, className }: PermissionSelectProps) {
  return (
    <div className={cn("inline-flex gap-1.5", className)} role="radiogroup" aria-label="참여자 권한">
      <Button
        type="button"
        size="sm"
        variant={value === "read" ? "default" : "secondary"}
        aria-pressed={value === "read"}
        disabled={disabled}
        onClick={() => onChange?.("read")}
      >
        읽기
      </Button>
      <Button
        type="button"
        size="sm"
        variant={value === "write" ? "default" : "secondary"}
        aria-pressed={value === "write"}
        disabled={disabled}
        onClick={() => onChange?.("write")}
      >
        읽기쓰기
      </Button>
    </div>
  );
}

export { PermissionSelect };
