"use client";

import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Button, buttonVariants } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { FormField } from "@/components/molecules/FormField";
import { cn } from "@/lib/utils";

export type Gender = "male" | "female" | "other";

export interface ProfileSectionProps {
  nickname: string;
  onNicknameChange: (value: string) => void;
  gender: Gender;
  onGenderChange: (value: Gender) => void;
  age: number | "";
  onAgeChange: (value: string) => void;
  avatarSrc?: string;
  avatarColor?: string;
  imagePreviewSrc?: string;
  imageError?: string;
  imageStatusMessage?: string;
  onImageSelect?: (file: File | null) => void;
  nicknameError?: string;
  ageError?: string;
  statusMessage?: string;
  isSaving?: boolean;
  hasChanges?: boolean;
  onSave: () => void;
  className?: string;
}

const GENDER_LABEL: Record<Gender, string> = {
  male: "남성",
  female: "여성",
  other: "기타",
};

function ProfileSection({
  nickname,
  onNicknameChange,
  gender,
  onGenderChange,
  age,
  onAgeChange,
  avatarSrc,
  avatarColor = "var(--brand-600)",
  imagePreviewSrc,
  imageError,
  imageStatusMessage,
  onImageSelect,
  nicknameError,
  ageError,
  statusMessage,
  isSaving = false,
  hasChanges = true,
  onSave,
  className,
}: ProfileSectionProps) {
  return (
    <div className={cn("flex flex-col gap-5", className)}>
      <div className="flex items-center gap-4">
        <Avatar className="h-16 w-16">
          {(imagePreviewSrc || avatarSrc) && (
            <AvatarImage
              src={imagePreviewSrc ?? avatarSrc}
              alt={`${nickname} 프로필 미리보기`}
            />
          )}
          <AvatarFallback
            role="img"
            aria-label={`${nickname || "사용자"} 프로필`}
            className="text-lg text-white"
            style={{ background: avatarColor }}
          >
            <span aria-hidden="true">{nickname.slice(0, 1)}</span>
          </AvatarFallback>
        </Avatar>
        {onImageSelect && (
          <div className="flex flex-col items-start gap-2">
            <label
              htmlFor="profile-image"
              aria-disabled={isSaving}
              className={cn(
                buttonVariants({ variant: "outline", size: "sm" }),
                isSaving && "cursor-not-allowed opacity-50",
              )}
            >
              프로필 이미지 변경
            </label>
            <input
              id="profile-image"
              type="file"
              className="sr-only"
              accept="image/jpeg,image/png,image/webp"
              disabled={isSaving}
              onChange={(event) => {
                onImageSelect(event.target.files?.[0] ?? null);
                event.target.value = "";
              }}
            />
          </div>
        )}
      </div>
      {(imageError || imageStatusMessage) && (
        <p
          role={imageError ? "alert" : "status"}
          className={cn(
            "text-sm font-medium",
            imageError ? "text-destructive-text" : "text-muted-foreground",
          )}
        >
          {imageError ?? imageStatusMessage}
        </p>
      )}

      <FormField label="닉네임" htmlFor="profile-nickname" error={nicknameError} required>
        <Input
          id="profile-nickname"
          value={nickname}
          maxLength={30}
          disabled={isSaving}
          aria-invalid={Boolean(nicknameError)}
          aria-describedby={nicknameError ? "profile-nickname-error" : undefined}
          onChange={(e) => onNicknameChange(e.target.value)}
          placeholder="닉네임을 입력하세요"
        />
      </FormField>

      <FormField label="성별" htmlFor="profile-gender">
        <Select
          value={gender}
          disabled={isSaving}
          onValueChange={(value) => onGenderChange(value as Gender)}
        >
          <SelectTrigger id="profile-gender" aria-label="성별 선택">
            <SelectValue>{GENDER_LABEL[gender]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="male">남성</SelectItem>
            <SelectItem value="female">여성</SelectItem>
            <SelectItem value="other">기타</SelectItem>
          </SelectContent>
        </Select>
      </FormField>

      <FormField label="나이" htmlFor="profile-age" error={ageError}>
        <Input
          id="profile-age"
          type="number"
          min={1}
          max={120}
          value={age}
          disabled={isSaving}
          aria-invalid={Boolean(ageError)}
          aria-describedby={ageError ? "profile-age-error" : undefined}
          onChange={(e) => onAgeChange(e.target.value)}
          placeholder="나이를 입력하세요"
        />
      </FormField>

      <div aria-live="polite" className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{statusMessage}</p>
        <Button disabled={isSaving || !hasChanges} onClick={onSave}>
          {isSaving ? "저장 중..." : "저장"}
        </Button>
      </div>
    </div>
  );
}

export { ProfileSection };
