"use client";

import { create } from "zustand";
import type { TripCardMember } from "@/components/organisms/TripCard";

export type TripRole = "생성자" | "읽기" | "읽기쓰기";

export interface TripSummary {
  id: string;
  title: string;
  dates: string;
  days: number;
  dday?: number | null;
  role: TripRole;
  mine: boolean;
  members: TripCardMember[];
}

interface TripState {
  trips: TripSummary[];
  removeTrip: (id: string) => void;
}

/** 백엔드 연동 전 mock 목록. IA 문서(KDT_Travel_Planner_ver01.xlsx)의 예시 데이터 기준. */
export const useTripStore = create<TripState>((set) => ({
  removeTrip: (id) => set((s) => ({ trips: s.trips.filter((t) => t.id !== id) })),
  trips: [
    {
      id: "1",
      title: "도쿄 벚꽃 여행",
      dates: "2027.04.02 - 04.05",
      days: 4,
      dday: 12,
      role: "생성자",
      mine: true,
      members: [
        { initial: "지", color: "#3b82f6" },
        { initial: "수", color: "#6366f1" },
      ],
    },
    {
      id: "2",
      title: "제주 힐링 캠핑",
      dates: "2027.05.14 - 05.17",
      days: 4,
      dday: 40,
      role: "생성자",
      mine: true,
      members: [{ initial: "지", color: "#3b82f6" }],
    },
    {
      id: "3",
      title: "부산 친구들과",
      dates: "2027.03.10 - 03.12",
      days: 3,
      role: "읽기쓰기",
      mine: false,
      members: [{ initial: "하", color: "#0ea5e9" }],
    },
    {
      id: "4",
      title: "방콕 미식 투어",
      dates: "2027.06.20 - 06.24",
      days: 5,
      role: "읽기",
      mine: false,
      members: [{ initial: "유", color: "#f97316" }],
    },
  ],
}));
