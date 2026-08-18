"use client";

import * as React from "react";
import { Bell } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface AppHeaderProps {
  loggedIn: boolean;
  userInitial?: string;
  nickname?: string;
  avatarColor?: string;
  avatarSrc?: string;
  onLogoClick?: () => void;
  onNotificationClick?: () => void;
  onProfileClick?: () => void;
  onLoginClick?: () => void;
  className?: string;
}

function AppHeader({
  loggedIn,
  userInitial = "지",
  nickname,
  avatarColor = "var(--brand-500)",
  avatarSrc,
  onLogoClick,
  onNotificationClick,
  onProfileClick,
  onLoginClick,
  className,
}: AppHeaderProps) {
  return (
    <header
      className={cn(
        "flex w-full min-w-0 items-center justify-between border-b border-border bg-background px-3 py-3 min-[320px]:px-4 sm:px-7",
        className
      )}
    >
      <button
        type="button"
        onClick={onLogoClick}
        className="flex min-w-0 shrink-0 cursor-pointer items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
          T
        </span>
        <span className="hidden text-base font-bold text-foreground min-[340px]:inline">TripPlanner</span>
      </button>

      {loggedIn ? (
        <div className="flex min-w-0 items-center gap-1.5 min-[320px]:gap-2 sm:gap-4">
          <button
            type="button"
            onClick={onNotificationClick}
            title="알림"
            className="flex h-[34px] w-[34px] shrink-0 cursor-pointer items-center justify-center rounded-md text-fg-secondary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icon icon={Bell} size="sm" aria-label="알림" />
          </button>
          {nickname && (
            <span
             className="hidden max-w-[120px] truncate text-sm font-medium text-foreground min-[420px]:inline"
             title={nickname}
            >
              {nickname}
            </span>
          )}

          <button
            type="button"
            onClick={onProfileClick}
            className="shrink-0 cursor-pointer rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Avatar className="h-8 w-8">
              {avatarSrc && <AvatarImage src={avatarSrc} alt={`${userInitial} 프로필`} />}
              <AvatarFallback className="text-white" style={{ background: avatarColor }}>
                {userInitial}
              </AvatarFallback>
            </Avatar>
          </button>
        </div>
      ) : (
        <Button onClick={onLoginClick}>로그인</Button>
      )}
    </header>
  );
}

export { AppHeader };
