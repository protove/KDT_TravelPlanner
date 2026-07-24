"use client";

import * as React from "react";
import { Check } from "lucide-react";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface PurposeTagSelectProps {
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
  className?: string;
}

function PurposeTagSelect({ options, selected, onToggle, className }: PurposeTagSelectProps) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    function handleOutsideClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {selected.map((tag) => (
        <div
          key={tag}
          className="flex items-center gap-1.5 rounded-full bg-accent py-1.5 pl-3 pr-2 text-sm font-semibold text-accent-foreground"
        >
          {tag}
          <button type="button"
          onClick={() => onToggle(tag)} className="opacity-700 hover:opacity-900">
            ×
          삭제
          </button>
        </div>
      ))}

      <div ref={containerRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-full border border-dashed border-border-strong px-3 py-1.5 text-sm font-semibold text-fg-secondary"
        >
          + 추가
        </button>
        {open && (
          <div className="absolute left-0 top-[calc(100%+6px)] z-20 min-w-[170px] rounded-lg bg-popover p-1.5 shadow-dialog">
            {options.map((option) => {
              const checked = selected.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => onToggle(option)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm text-foreground hover:bg-muted"
                >
                  <span>{option}</span>
                  {checked && <Icon icon={Check} size="sm" className="text-primary" aria-label="선택됨" />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export { PurposeTagSelect };
