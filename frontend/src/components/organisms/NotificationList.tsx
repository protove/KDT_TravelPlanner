import * as React from "react";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export interface TripInviteNotification {
  id: string;
  inviterName: string;
  tripTitle: string;
}

export interface NotificationListProps {
  notifications: TripInviteNotification[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  emptyMessage?: string;
  className?: string;
}

function NotificationList({
  notifications,
  onAccept,
  onReject,
  emptyMessage = "받은 초대가 없어요.",
  className,
}: NotificationListProps) {
  if (notifications.length === 0) {
    return <p className="py-10 text-center text-sm text-muted-foreground">{emptyMessage}</p>;
  }

  return (
    <div className={cn("flex flex-col gap-2.5", className)}>
      {notifications.map((n) => (
        <div key={n.id} className="rounded-xl bg-card p-3.5 shadow-card">
          <p className="mb-2.5 text-sm text-foreground">
            <b>{n.inviterName}</b>님이 &quot;{n.tripTitle}&quot;에 초대했어요.
          </p>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => onAccept(n.id)}>
              수락
            </Button>
            <Button size="sm" variant="outline" onClick={() => onReject(n.id)}>
              거절
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

export { NotificationList };
