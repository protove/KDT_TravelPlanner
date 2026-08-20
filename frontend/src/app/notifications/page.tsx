"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { NotificationList } from "@/components/organisms/NotificationList";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useNotificationStore } from "@/lib/stores/useNotificationStore";

export default function NotificationsPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((state) => state.isLoggedIn);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const user = useAuthStore((state) => state.user);

  const notifications = useNotificationStore((state) => state.notifications);
  const isLoading = useNotificationStore((state) => state.isLoading);
  const error = useNotificationStore((state) => state.error);
  const load = useNotificationStore((state) => state.load);
  const accept = useNotificationStore((state) => state.accept);
  const reject = useNotificationStore((state) => state.reject);

  React.useEffect(() => {
    if (!isInitializing && !isLoggedIn) {
      router.replace("/");
      return;
    }

    if (!isInitializing && isLoggedIn) void load();
  }, [isInitializing, isLoggedIn, load, router]);

  if (isInitializing || !isLoggedIn || !user) return null;

  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">알림</h1>}
    >
      {isLoading ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          받은 초대를 불러오는 중입니다.
        </p>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center gap-3 py-10 text-center"
        >
          <p className="text-sm text-destructive">{error}</p>
          <Button variant="outline" onClick={() => void load()}>
            다시 시도
          </Button>
        </div>
      ) : (
        <NotificationList
          notifications={notifications}
          onAccept={(id) => void accept(id)}
          onReject={(id) => void reject(id)}
        />
      )}
    </ListLayout>
  );
}
