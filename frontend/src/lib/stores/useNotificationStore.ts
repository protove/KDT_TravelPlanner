"use client";

import { create } from "zustand";
import type { TripInviteNotification } from "@/components/organisms/NotificationList";

interface NotificationState {
  notifications: TripInviteNotification[];
  accept: (invitationId: string) => void;
  reject: (invitationId: string) => void;
}

/**
 * 백엔드 연동 전 Mock 초대 알림 목록.
 *
 * 실제 API 연동 시:
 * PATCH /api/v1/travel-invitations/{invitationId}
 * Body: { "action": "ACCEPT" | "REJECT" }
 */
export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [
    {
      id: "1",
      inviterName: "박수아",
      tripTitle: "도쿄 벚꽃 여행",
    },
    {
      id: "2",
      inviterName: "이하늘",
      tripTitle: "부산 친구들과",
    },
  ],

  accept: (invitationId) => {
    console.info(
      `[MOCK] PATCH /api/v1/travel-invitations/${invitationId}`,
      { action: "ACCEPT" },
    );

    set((state) => ({
      notifications: state.notifications.filter(
        (notification) => notification.id !== invitationId,
      ),
    }));
  },

  reject: (invitationId) => {
    console.info(
      `[MOCK] PATCH /api/v1/travel-invitations/${invitationId}`,
      { action: "REJECT" },
    );

    set((state) => ({
      notifications: state.notifications.filter(
        (notification) => notification.id !== invitationId,
      ),
    }));
  },
}));