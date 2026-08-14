"use client";

import Image from "next/image";
import * as React from "react";
import { Avatar, AvatarFallback } from "@/components/atoms/Avatar";
import { Badge } from "@/components/atoms/Badge";
import { Skeleton } from "@/components/atoms/Skeleton";
import { cn } from "@/lib/utils";

export interface TripCardMember {
  initial: string;
  color: string;
}

export interface TripCardProps {
  title: string;
  dates: string;
  days: number;
  dday?: number | null;
  /** 제공되면 D-day 배지 대신 표시 — 공유받은 일정 탭처럼 권한을 보여줘야 할 때 사용 */
  role?: string;
  members?: TripCardMember[];
  thumbnailSrc?: string;
  isPast?: boolean;
  onClick?: () => void;
  className?: string;
}

interface TripThumbnailProps {
  src?: string;
  alt: string;
}

function TripThumbnail({ src, alt }: TripThumbnailProps) {
  const [isLoaded, setIsLoaded] = React.useState(false);
  const [hasError, setHasError] = React.useState(false);

  return (
    <div className="relative h-[140px] overflow-hidden bg-muted">
      {src && !hasError ? (
        <>
          {!isLoaded && (
            <Skeleton
              aria-label="여행 썸네일을 불러오는 중"
              className="absolute inset-0 z-10 h-full w-full rounded-none"
            />
          )}
          <Image
            src={src}
            alt={alt}
            fill
            unoptimized
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
            className={cn(
              "object-cover transition-opacity duration-300",
              isLoaded ? "opacity-100" : "opacity-0",
            )}
            onLoad={() => setIsLoaded(true)}
            onError={() => {
              setHasError(true);
              setIsLoaded(true);
            }}
          />
        </>
      ) : (
        <div
          role="img"
          aria-label={`${alt} 대체 이미지`}
          className="flex h-full items-center justify-center font-mono text-xs tracking-wide text-fg-secondary"
          style={{
            background:
              "repeating-linear-gradient(135deg, var(--brand-100), var(--brand-100) 10px, var(--brand-200) 10px, var(--brand-200) 20px)",
          }}
        >
          여행 사진
        </div>
      )}
    </div>
  );
}

function TripCard({
  title,
  dates,
  days,
  dday,
  role,
  members = [],
  thumbnailSrc,
  isPast = false,
  onClick,
  className,
}: TripCardProps) {
  const showDday = !isPast && !role && dday != null;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onClick?.();
      }}
      className={cn(
        "cursor-pointer overflow-hidden rounded-xl bg-card shadow-card transition-shadow hover:shadow-dialog",
        className,
      )}
    >
      <TripThumbnail
        key={thumbnailSrc ?? "fallback"}
        src={thumbnailSrc}
        alt={`${title} 대표 이미지`}
      />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2.5">
          <div className="min-w-0">
            <div className="truncate text-base font-bold text-foreground" title={title}>
              {title}
            </div>
            <div className="mt-0.5 text-sm text-muted-foreground">{dates}</div>
          </div>
          {role ? (
            <Badge variant="secondary" className="whitespace-nowrap">
              {role}
            </Badge>
          ) : (
            showDday && (
              <Badge variant="accent" className="whitespace-nowrap">
                D-{dday}
              </Badge>
            )
          )}
        </div>
        <div className="mt-3.5 flex items-center justify-between">
          <div className="flex">
            {members.map((member, index) => (
              <Avatar
                key={`${member.initial}-${index}`}
                className="h-[26px] w-[26px] ring-2 ring-background"
                style={index > 0 ? { marginLeft: "-8px" } : undefined}
              >
                <AvatarFallback
                  className="text-xs text-white"
                  style={{ background: member.color }}
                >
                  {member.initial}
                </AvatarFallback>
              </Avatar>
            ))}
          </div>
          {isPast ? (
            <span className="text-sm font-bold text-primary">앨범 보기</span>
          ) : (
            <span className="text-xs text-muted-foreground">{days}일 일정</span>
          )}
        </div>
      </div>
    </div>
  );
}

function TripCardSkeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "overflow-hidden rounded-xl bg-card shadow-card",
        className,
      )}
    >
      <Skeleton className="h-[140px] w-full rounded-none" />
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
          </div>
          <Skeleton className="h-6 w-12 rounded-full" />
        </div>
        <div className="flex items-center justify-between">
          <div className="flex gap-1">
            <Skeleton className="h-[26px] w-[26px] rounded-full" />
            <Skeleton className="h-[26px] w-[26px] rounded-full" />
          </div>
          <Skeleton className="h-4 w-14" />
        </div>
      </div>
    </div>
  );
}

export { TripCard, TripCardSkeleton };
