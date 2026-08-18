import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { cn } from "@/lib/utils";

export interface UserChipProps {
  name: string;
  avatarSrc?: string;
  avatarColor?: string;
  className?: string;
}

function UserChip({
  name,
  avatarSrc,
  avatarColor,
  className,
}: UserChipProps) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <Avatar className="h-8 w-8 shrink-0">
        {avatarSrc && <AvatarImage src={avatarSrc} alt={name} />}

        <AvatarFallback
          className={avatarColor ? "text-white" : undefined}
          style={avatarColor ? { background: avatarColor } : undefined}
        >
          {name.slice(0, 1)}
        </AvatarFallback>
      </Avatar>

      <span
        className="min-w-0 truncate text-sm font-medium text-foreground"
        title={name}
      >
        {name}
      </span>
    </div>
  );
}

export { UserChip };