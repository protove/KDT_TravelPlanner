"use client";

import { create } from "zustand";
import type { Gender } from "@/components/organisms/ProfileSection";
import type { AuthProvider } from "@/lib/types/auth";

export type { Gender, AuthProvider };

export interface AuthUser {
  nickname: string;
  initial: string;
  avatarColor: string;
  gender: Gender;
  age: number | "";
}

interface AuthState {
  isLoggedIn: boolean;
  user: AuthUser | null;
  accessToken: string | null;
  setSession: (accessToken: string, user: AuthUser) => void;
  logout: () => void;
  updateProfile: (patch: Partial<Pick<AuthUser, "nickname" | "gender" | "age">>) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  isLoggedIn: false,
  user: null,
  accessToken: null,
  setSession: (accessToken, user) => set({ isLoggedIn: true, accessToken, user }),
  logout: () => set({ isLoggedIn: false, user: null, accessToken: null }),
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
