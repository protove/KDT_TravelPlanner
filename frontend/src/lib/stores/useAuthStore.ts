"use client";

import { create } from "zustand";

export type AuthProvider = "google" | "naver";

export interface AuthUser {
  nickname: string;
  initial: string;
  avatarColor: string;
}

interface AuthState {
  isLoggedIn: boolean;
  user: AuthUser | null;
  login: (provider: AuthProvider) => void;
  logout: () => void;
}

/**
 * 백엔드 연동 전 mock. 실제로는 SSO 콜백 후 서버가 내려주는 JWT+세션과
 * 자동 생성된 닉네임으로 대체된다 (IA 문서: "가입 시 닉네임 자동 생성").
 */
const MOCK_USER_BY_PROVIDER: Record<AuthProvider, AuthUser> = {
  google: { nickname: "여행자3021", initial: "여", avatarColor: "#3b82f6" },
  naver: { nickname: "여행자8842", initial: "여", avatarColor: "#03c75a" },
};

export const useAuthStore = create<AuthState>((set) => ({
  isLoggedIn: false,
  user: null,
  login: (provider) => set({ isLoggedIn: true, user: MOCK_USER_BY_PROVIDER[provider] }),
  logout: () => set({ isLoggedIn: false, user: null }),
}));
