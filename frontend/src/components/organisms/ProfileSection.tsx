"use client";

import * as React from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/atoms/Avatar";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { FormField } from "@/components/molecules/FormField";
import { cn } from "@/lib/utils";

export type Gender = "male" | "female" | "unspecified";

export interface ProfileSectionProps {
  nickname: string;
  onNicknameChange: (value: string) => void;
  gender: Gender;
  onGenderChange: (value: Gender) => void;
  age: number | "";
  onAgeChange: (value: string) => void;
  avatarSrc?: string;
  avatarColor?: string;
  onSave: () => void;
  className?: string;
}

const GENDER_LABEL: Record<Gender, string> = {
  male: "남성",
  female: "여성",
  unspecified: "선택 안 함",
};

function ProfileSection({
  nickname,
  onNicknameChange,
  gender,
  onGenderChange,
  age,
  onAgeChange,
  avatarSrc,
  avatarColor = "var(--brand-500)",
  onSave,
  className,
}: ProfileSectionProps) {
  return (
    <div className={cn("flex flex-col gap-5", className)}>
      <Avatar className="h-16 w-16">
        {avatarSrc && <AvatarImage src={avatarSrc} alt={nickname} />}
        <AvatarFallback className="text-lg text-white" style={{ background: avatarColor }}>
          {nickname.slice(0, 1)}
        </AvatarFallback>
      </Avatar>

      <FormField label="닉네임" htmlFor="profile-nickname">
        <Input
          id="profile-nickname"
          value={nickname}
          onChange={(e) => onNicknameChange(e.target.value)}
          placeholder="닉네임을 입력하세요"
        />
      </FormField>

      <FormField label="성별" htmlFor="profile-gender">
        <Select value={gender} onValueChange={(value) => onGenderChange(value as Gender)}>
          <SelectTrigger id="profile-gender">
            <SelectValue>{GENDER_LABEL[gender]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="male">남성</SelectItem>
            <SelectItem value="female">여성</SelectItem>
            <SelectItem value="unspecified">선택 안 함</SelectItem>
          </SelectContent>
        </Select>
      </FormField>

      <FormField label="나이" htmlFor="profile-age">
        <Input
          id="profile-age"
          type="number"
          value={age}
          onChange={(e) => onAgeChange(e.target.value)}
          placeholder="나이를 입력하세요"
        />
      </FormField>

      <div className="flex justify-end">
        <Button onClick={onSave}>저장</Button>
      </div>
    </div>
  );
}

export { ProfileSection };
