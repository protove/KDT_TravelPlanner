import { apiFetch } from "@/lib/api/client";
import type { UserProfile } from "@/lib/api/profile";

export const MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024;

export const PROFILE_IMAGE_CONTENT_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export type ProfileImageContentType =
  (typeof PROFILE_IMAGE_CONTENT_TYPES)[number];

export interface ProfileImageUploadUrlResponse {
  uploadUrl: string;
  objectKey: string;
  expiresAt: string;
}

export type ProfileImageUploadStage =
  | "validation"
  | "upload-url"
  | "s3-put"
  | "complete";

export class ProfileImageUploadError extends Error {
  constructor(
    public readonly stage: ProfileImageUploadStage,
    message: string,
  ) {
    super(message);
    this.name = "ProfileImageUploadError";
  }
}

function isSupportedContentType(
  contentType: string,
): contentType is ProfileImageContentType {
  return PROFILE_IMAGE_CONTENT_TYPES.some(
    (supportedType) => supportedType === contentType,
  );
}

export function validateProfileImage(file: File): void {
  if (!isSupportedContentType(file.type)) {
    throw new ProfileImageUploadError(
      "validation",
      "JPEG, PNG, WebP 형식의 이미지만 사용할 수 있어요.",
    );
  }

  if (file.size < 1 || file.size > MAX_PROFILE_IMAGE_SIZE) {
    throw new ProfileImageUploadError(
      "validation",
      "프로필 이미지는 5MB 이하여야 해요.",
    );
  }
}

export function requestProfileImageUploadUrl(
  accessToken: string,
  file: File,
): Promise<ProfileImageUploadUrlResponse> {
  validateProfileImage(file);

  return apiFetch<ProfileImageUploadUrlResponse>(
    "/api/v1/users/me/profile-image/upload-url",
    accessToken,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contentType: file.type,
        fileSize: file.size,
      }),
    },
  );
}

export async function putProfileImageToStorage(
  uploadUrl: string,
  file: File,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  });

  if (!response.ok) {
    throw new ProfileImageUploadError(
      "s3-put",
      "이미지 업로드에 실패했어요. 새 업로드 URL로 다시 시도해 주세요.",
    );
  }
}

export function completeProfileImageUpload(
  accessToken: string,
  objectKey: string,
): Promise<UserProfile> {
  return apiFetch<UserProfile>(
    "/api/v1/users/me/profile-image/complete",
    accessToken,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ objectKey }),
    },
  );
}

export async function uploadProfileImage(
  accessToken: string,
  file: File,
): Promise<UserProfile> {
  validateProfileImage(file);

  let uploadData: ProfileImageUploadUrlResponse;

  try {
    uploadData = await requestProfileImageUploadUrl(accessToken, file);
  } catch (error) {
    if (error instanceof ProfileImageUploadError) throw error;
    throw new ProfileImageUploadError(
      "upload-url",
      "이미지 업로드 준비에 실패했어요.",
    );
  }

  await putProfileImageToStorage(uploadData.uploadUrl, file);

  try {
    return await completeProfileImageUpload(accessToken, uploadData.objectKey);
  } catch {
    throw new ProfileImageUploadError(
      "complete",
      "이미지는 업로드됐지만 프로필 반영에 실패했어요.",
    );
  }
}
