"use client";

import { useRouter } from "next/navigation";
import { AppHeader } from "@/components/organisms/AppHeader";
import { NotificationList } from "@/components/organisms/NotificationList";
import { ListLayout } from "@/components/templates/ListLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useNotificationStore } from "@/lib/stores/useNotificationStore";

export default function NotificationsPage() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);

  const notifications = useNotificationStore((state) => state.notifications);
  const accept = useNotificationStore((state) => state.accept);
  const reject = useNotificationStore((state) => state.reject);

  return (
    <ListLayout
      header={
        <AppHeader
          loggedIn
          userInitial={user?.initial}
          avatarColor={user?.avatarColor}
          onLogoClick={() => router.push("/trips")}
          onProfileClick={() => router.push("/mypage")}
          onNotificationClick={() => router.push("/notifications")}
        />
      }
      title={<h1 className="text-2xl font-bold text-foreground">알림</h1>}
    >
      <NotificationList
        notifications={notifications}
        onAccept={accept}
        onReject={reject}
      />
    </ListLayout>
  );
}