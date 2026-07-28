import { apiFetch } from "@/lib/api/client";
import type { UserProfile } from "@/lib/api/profile";

const MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024;
const ALLOWED_PROFILE_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export interface ProfileImageUploadUrlResponse {
  uploadUrl: string;
  objectKey: string;
  expiresAt: string;
}

export type ProfileImageUploadStep =
  | "requesting-url"
  | "uploading"
  | "completing";

export class ProfileImageUploadError extends Error {
  constructor(
    message: string,
    public step: "validation" | "storage",
  ) {
    super(message);
    this.name = "ProfileImageUploadError";
  }
}

export function validateProfileImage(file: File): void {
  if (!ALLOWED_PROFILE_IMAGE_TYPES.has(file.type)) {
    throw new ProfileImageUploadError(
      "JPEG, PNG, WebP 형식의 이미지만 선택할 수 있어요.",
      "validation",
    );
  }

  if (file.size < 1 || file.size > MAX_PROFILE_IMAGE_SIZE) {
    throw new ProfileImageUploadError(
      "프로필 이미지는 5MiB 이하로 선택해 주세요.",
      "validation",
    );
  }
}

function createProfileImageUploadUrl(
  accessToken: string,
  file: File,
): Promise<ProfileImageUploadUrlResponse> {
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

async function putProfileImage(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
    credentials: "omit",
  });

  if (!response.ok) {
    throw new ProfileImageUploadError(
      response.status === 403
        ? "업로드 주소가 만료되었어요. 다시 시도해 주세요."
        : "이미지를 저장소에 업로드하지 못했어요.",
      "storage",
    );
  }
}

function completeProfileImageUpload(
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
  onStep?: (step: ProfileImageUploadStep) => void,
): Promise<UserProfile> {
  validateProfileImage(file);

  onStep?.("requesting-url");
  const uploadData = await createProfileImageUploadUrl(accessToken, file);

  onStep?.("uploading");
  await putProfileImage(uploadData.uploadUrl, file);

  onStep?.("completing");
  return completeProfileImageUpload(accessToken, uploadData.objectKey);
}
