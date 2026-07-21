"use client";

import { create } from "zustand";
import type { Gender } from "@/components/organisms/ProfileSection";

export type AuthProvider = "google" | "naver";
export type { Gender };

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
  login: (provider: AuthProvider) => void;
  logout: () => void;
  updateProfile: (patch: Partial<Pick<AuthUser, "nickname" | "gender" | "age">>) => void;
}

/**
 * 백엔드 연동 전 mock. 실제로는 SSO 콜백 후 서버가 내려주는 JWT+세션과
 * 자동 생성된 닉네임으로 대체된다 (IA 문서: "가입 시 닉네임 자동 생성").
 */
const MOCK_USER_BY_PROVIDER: Record<AuthProvider, AuthUser> = {
  google: { nickname: "여행자3021", initial: "여", avatarColor: "#3b82f6", gender: "unspecified", age: "" },
  naver: { nickname: "여행자8842", initial: "여", avatarColor: "#03c75a", gender: "unspecified", age: "" },
};

export const useAuthStore = create<AuthState>((set) => ({
  isLoggedIn: false,
  user: null,
  login: (provider) => {
    document.cookie = "logged_in=1; path=/; max-age=86400";
    set({ isLoggedIn: true, user: MOCK_USER_BY_PROVIDER[provider] });
  },
  logout: () => {
    document.cookie = "logged_in=; path=/; max-age=0";
    set({ isLoggedIn: false, user: null });
  },
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
