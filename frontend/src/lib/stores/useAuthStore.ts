"use client";

import { create } from "zustand";
import type { Gender } from "@/components/organisms/ProfileSection";
import type { AuthProvider } from "@/lib/types/auth";

export type { Gender, AuthProvider };

export interface AuthUser {
  provider: AuthProvider;
  name: string | null;
  nickname: string;
  initial: string;
  avatarColor: string;
  profileImageUrl: string | null;
  gender: Gender;
  birthYear: number | "";
}

interface AuthState {
  isLoggedIn: boolean;
  user: AuthUser | null;
  accessToken: string | null;
  /**
   * 앱이 막 부팅돼서 새로고침 후 세션 복구(silent refresh)가 아직 안 끝난 상태.
   * true인 동안은 isLoggedIn 값을 신뢰하면 안 된다 (기본값 false라서 오판하기 쉬움).
   */
  isInitializing: boolean;
  setSession: (accessToken: string, user: AuthUser) => void;
  /** apiFetch가 401을 만나 조용히 재발급받은 access token만 반영할 때 쓴다(user는 그대로 유지). */
  setAccessToken: (accessToken: string) => void;
  logout: () => void;
  finishInitializing: () => void;
  updateProfile: (
    patch: Partial<
      Pick<AuthUser, "nickname" | "gender" | "birthYear" | "profileImageUrl">
    >,
  ) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isLoggedIn: false,
  user: null,
  accessToken: null,
  isInitializing: true,
  setSession: (accessToken, user) => {
    document.cookie = "logged_in=1; path=/; max-age=604800";
    set({ isLoggedIn: true, accessToken, user });
  },
  setAccessToken: (accessToken) => set({ accessToken }),
  logout: () => {
    document.cookie = "logged_in=; path=/; max-age=0";
    set({ isLoggedIn: false, user: null, accessToken: null });
  },
  finishInitializing: () => set({ isInitializing: false }),
  updateProfile: (patch) =>
    set((s) => {
      if (!s.user) return s;
      const nickname = patch.nickname ?? s.user.nickname;
      return {
        user: {
          ...s.user,
          ...patch,
          nickname,
          initial: nickname.slice(0, 1) || s.user.initial,
        },
      };
    }),
}));
