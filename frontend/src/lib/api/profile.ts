import { apiFetch } from "@/lib/api/client";

export type ProfileGender = "MALE" | "FEMALE" | "OTHER" | "UNSPECIFIED";

export interface UserProfile {
  userId: string;
  provider: "GOOGLE" | "NAVER";
  email: string | null;
  name: string | null;
  nickname: string | null;
  profileImageUrl: string | null;
  gender: ProfileGender | null;
  birthYear: number | null;
  isProfileCompleted: boolean;
}

export interface UserProfileUpdateRequest {
  nickname?: string;
  profileImageUrl?: string | null;
  gender?: ProfileGender | null;
  birthYear?: number | null;
}

export function getProfile(accessToken: string): Promise<UserProfile> {
  return apiFetch<UserProfile>("/api/v1/users/me/profile", accessToken);
}

export function updateUserProfile(
  accessToken: string,
  request: UserProfileUpdateRequest,
): Promise<UserProfile> {
  return apiFetch<UserProfile>("/api/v1/users/me/profile", accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function deleteAccount(accessToken: string): Promise<void> {
  return apiFetch<void>("/api/v1/users/me", accessToken, {
    method: "DELETE",
  });
}
