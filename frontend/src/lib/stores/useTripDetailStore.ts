"use client";

import { create } from "zustand";
import type { TripCardMember } from "@/components/organisms/TripCard";

export interface Place {
  id: string;
  name: string;
  note: string;
  /** null = 미배정 목록 */
  day: number | null;
  pos: { top: string; left: string };
}

export interface CommentItem {
  id: string;
  name: string;
  avatarColor: string;
  timeLabel: string;
  text: string;
}

export interface TripDetailInfo {
  title: string;
  country: string;
  city: string;
  companion: string;
  purposes: string[];
  dateRange: { start: Date; end: Date };
  description: string;
}

interface TripDetailState {
  info: TripDetailInfo;
  members: TripCardMember[];
  places: Place[];
  comments: CommentItem[];
  setCountry: (v: string) => void;
  setCity: (v: string) => void;
  setCompanion: (v: string) => void;
  setDescription: (v: string) => void;
  setDateRange: (range: { start: Date; end: Date }) => void;
  togglePurpose: (purpose: string) => void;
  addPlace: (place: Omit<Place, "id">) => void;
  updatePlace: (id: string, patch: Partial<Place>) => void;
  removePlace: (id: string) => void;
  addComment: (comment: Omit<CommentItem, "id">) => void;
}

export const COMPANION_OPTIONS = ["혼자", "연인과", "가족과", "친구와", "반려동물과", "기타"];
export const PURPOSE_OPTIONS = ["휴양 · 자연", "관광 · 명소", "미식", "액티비티/체험", "쇼핑", "기타"];

/** 백엔드 연동 전 mock. 여행일정 id="1"(도쿄 벚꽃 여행) 상세 데이터. */
export const useTripDetailStore = create<TripDetailState>((set) => ({
  info: {
    title: "도쿄 벚꽃 여행",
    country: "일본",
    city: "도쿄",
    companion: "친구와",
    purposes: ["휴양 · 자연"],
    dateRange: { start: new Date(2027, 3, 2), end: new Date(2027, 3, 5) },
    description: "",
  },
  members: [
    { initial: "지", color: "#3b82f6" },
    { initial: "수", color: "#6366f1" },
    { initial: "하", color: "#0ea5e9" },
  ],
  places: [
    { id: "1", name: "나리타 국제공항", note: "도착 후 리무진버스로 이동", day: 0, pos: { top: "20%", left: "20%" } },
    { id: "2", name: "아사쿠사 센소지", note: "참배 후 나카미세 거리 구경", day: 0, pos: { top: "40%", left: "35%" } },
    { id: "3", name: "텐도쿄 아사쿠사점", note: "텐푸라 런치", day: 0, pos: { top: "55%", left: "48%" } },
    { id: "4", name: "메이지 신궁", note: "", day: 1, pos: { top: "30%", left: "60%" } },
    { id: "5", name: "시부야 스크램블", note: "쇼핑 및 저녁", day: 1, pos: { top: "48%", left: "70%" } },
    { id: "6", name: "가와고에 구시가", note: "", day: 2, pos: { top: "65%", left: "55%" } },
    { id: "7", name: "우에노 공원", note: "벚꽃 산책 후보지", day: null, pos: { top: "25%", left: "78%" } },
    { id: "8", name: "카가 거리", note: "", day: null, pos: { top: "75%", left: "25%" } },
  ],
  comments: [
    { id: "1", name: "이하늘", avatarColor: "#0ea5e9", timeLabel: "3시간 전", text: "경로 순서 좋네요!" },
  ],
  setCountry: (v) => set((s) => ({ info: { ...s.info, country: v } })),
  setCity: (v) => set((s) => ({ info: { ...s.info, city: v } })),
  setCompanion: (v) => set((s) => ({ info: { ...s.info, companion: v } })),
  setDescription: (v) => set((s) => ({ info: { ...s.info, description: v } })),
  setDateRange: (range) => set((s) => ({ info: { ...s.info, dateRange: range } })),
  togglePurpose: (purpose) =>
    set((s) => ({
      info: {
        ...s.info,
        purposes: s.info.purposes.includes(purpose)
          ? s.info.purposes.filter((p) => p !== purpose)
          : [...s.info.purposes, purpose],
      },
    })),
  addPlace: (place) => set((s) => ({ places: [...s.places, { ...place, id: crypto.randomUUID() }] })),
  updatePlace: (id, patch) =>
    set((s) => ({ places: s.places.map((p) => (p.id === id ? { ...p, ...patch } : p)) })),
  removePlace: (id) => set((s) => ({ places: s.places.filter((p) => p.id !== id) })),
  addComment: (comment) => set((s) => ({ comments: [...s.comments, { ...comment, id: crypto.randomUUID() }] })),
}));
