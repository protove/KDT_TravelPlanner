"use client";

import { create } from "zustand";
import type { TripInviteNotification } from "@/components/organisms/NotificationList";
import { fetchAuthUser, refreshAccessToken } from "@/lib/api/auth";
import { useAuthStore } from "@/lib/stores/useAuthStore";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

interface ApiResponse<T> {
  data: T;
}

interface PageResponse<T> {
  content: T[];
}

interface ReceivedTravelInvitation {
  invitationId: string;
  travel: {
    title: string;
  };
  inviter: {
    nickname: string | null;
  };
}

interface NotificationState {
  notifications: TripInviteNotification[];
  isLoading: boolean;
  error: string | null;
  load: () => Promise<void>;
  accept: (invitationId: string) => Promise<void>;
  reject: (invitationId: string) => Promise<void>;
}

let refreshPromise: Promise<string> | null = null;

async function getAccessToken(forceRefresh = false): Promise<string> {
  const currentAccessToken = useAuthStore.getState().accessToken;
  if (!forceRefresh && currentAccessToken) return currentAccessToken;

  if (!refreshPromise) {
    refreshPromise = (async () => {
      const accessToken = await refreshAccessToken();
      if (!accessToken) throw new Error("로그인이 필요합니다.");

      const user = await fetchAuthUser(accessToken);
      useAuthStore.getState().setSession(accessToken, user);
      return accessToken;
    })().finally(() => {
      refreshPromise = null;
    });
  }

  return refreshPromise;
}

async function authorizedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  async function request(forceRefresh = false) {
    const accessToken = await getAccessToken(forceRefresh);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);

    return fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      credentials: "include",
    });
  }

  const response = await request();
  return response.status === 401 ? request(true) : response;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`초대 API 요청에 실패했습니다. (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

async function respondToInvitation(
  invitationId: string,
  action: "ACCEPT" | "REJECT",
): Promise<void> {
  const response = await authorizedFetch(
    `/api/v1/travel-invitations/${encodeURIComponent(invitationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    },
  );

  await parseResponse<unknown>(response);
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  isLoading: false,
  error: null,

  load: async () => {
    set({ isLoading: true, error: null });

    try {
      const query = new URLSearchParams({
        status: "PENDING",
        page: "0",
        size: "20",
      });
      const response = await authorizedFetch(
        `/api/v1/users/me/travel-invitations?${query.toString()}`,
      );
      const body = await parseResponse<
        ApiResponse<PageResponse<ReceivedTravelInvitation>>
      >(response);
      const notifications = body.data.content.map((invitation) => ({
        id: invitation.invitationId,
        inviterName: invitation.inviter.nickname ?? "알 수 없는 사용자",
        tripTitle: invitation.travel.title,
      }));

      set({ notifications, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        error:
          error instanceof Error
            ? error.message
            : "받은 초대를 불러오지 못했습니다.",
      });
    }
  },

  accept: async (invitationId) => {
    set({ error: null });
    try {
      await respondToInvitation(invitationId, "ACCEPT");
      set((state) => ({
        notifications: state.notifications.filter(
          (notification) => notification.id !== invitationId,
        ),
      }));
    } catch (error) {
      set({
        error:
          error instanceof Error ? error.message : "초대를 수락하지 못했습니다.",
      });
    }
  },

  reject: async (invitationId) => {
    set({ error: null });
    try {
      await respondToInvitation(invitationId, "REJECT");
      set((state) => ({
        notifications: state.notifications.filter(
          (notification) => notification.id !== invitationId,
        ),
      }));
    } catch (error) {
      set({
        error:
          error instanceof Error ? error.message : "초대를 거절하지 못했습니다.",
      });
    }
  },
}));
