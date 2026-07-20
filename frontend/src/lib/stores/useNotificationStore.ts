"use client";

import { create } from "zustand";
import type { TripInviteNotification } from "@/components/organisms/NotificationList";

interface NotificationState {
  notifications: TripInviteNotification[];
  accept: (id: string) => void;
  reject: (id: string) => void;
}

/** 백엔드 연동 전 mock 초대 알림 목록. */
export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [
    { id: "1", inviterName: "박수아", tripTitle: "도쿄 벚꽃 여행" },
    { id: "2", inviterName: "이하늘", tripTitle: "부산 친구들과" },
  ],
  accept: (id) => set((s) => ({ notifications: s.notifications.filter((n) => n.id !== id) })),
  reject: (id) => set((s) => ({ notifications: s.notifications.filter((n) => n.id !== id) })),
}));
