"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { ProfileSection } from "@/components/organisms/ProfileSection";
import { NotificationList } from "@/components/organisms/NotificationList";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { MyPageLayout } from "@/components/templates/MyPageLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useNotificationStore } from "@/lib/stores/useNotificationStore";
import {
  fetchAuthUser,
  mapProfile,
  refreshAccessToken,
  requestLogout,
} from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import {
  deleteAccount,
  getProfile,
  type ProfileGender,
  type UserProfile,
  updateUserProfile,
} from "@/lib/api/profile";
import {
  ProfileImageUploadError,
  type ProfileImageUploadStep,
  uploadProfileImage,
  validateProfileImage,
} from "@/lib/api/profileImage";
import type { Gender } from "@/components/organisms/ProfileSection";

type MypageTab = "profile" | "notif";

const TABS = [
  { key: "profile", label: "프로필수정" },
  { key: "notif", label: "초대알림" },
];

interface ProfileDraft {
  nickname: string;
  gender: Gender;
  age: number | "";
}

function mapGenderToForm(gender: ProfileGender | null): Gender {
  if (gender === "MALE") return "male";
  if (gender === "FEMALE") return "female";
  return "other";
}

function mapGenderToApi(gender: Gender): ProfileGender {
  if (gender === "male") return "MALE";
  if (gender === "female") return "FEMALE";
  if (gender === "other") return "OTHER";
  return "OTHER";
}

function profileToDraft(profile: UserProfile): ProfileDraft {
  const currentYear = new Date().getFullYear();
  return {
    nickname: profile.nickname ?? profile.name ?? "",
    gender: mapGenderToForm(profile.gender),
    age: profile.birthYear ? currentYear - profile.birthYear : "",
  };
}

export default function MypagePage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);
  const setSession = useAuthStore((s) => s.setSession);
  const updateAuthProfile = useAuthStore((s) => s.updateProfile);
  const logout = useAuthStore((s) => s.logout);
  const notifications = useNotificationStore((s) => s.notifications);
  const acceptNotification = useNotificationStore((s) => s.accept);
  const rejectNotification = useNotificationStore((s) => s.reject);

  const [tab, setTab] = React.useState<MypageTab>("profile");
  const [showWithdraw, setShowWithdraw] = React.useState(false);
  const [profile, setProfile] = React.useState<UserProfile | null>(null);
  const [draft, setDraft] = React.useState<ProfileDraft>({
    nickname: "",
    gender: "other",
    age: "",
  });
  const [isLoadingProfile, setIsLoadingProfile] = React.useState(true);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isWithdrawing, setIsWithdrawing] = React.useState(false);
  const [profileError, setProfileError] = React.useState<string | null>(null);
  const [nicknameError, setNicknameError] = React.useState<string | undefined>();
  const [ageError, setAgeError] = React.useState<string | undefined>();
  const [statusMessage, setStatusMessage] = React.useState<string | undefined>();
  const [selectedImage, setSelectedImage] = React.useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = React.useState<string>();
  const [imageError, setImageError] = React.useState<string>();
  const [imageStatusMessage, setImageStatusMessage] = React.useState<string>();
  const [imageUploadStep, setImageUploadStep] =
    React.useState<ProfileImageUploadStep>();

  React.useEffect(
    () => () => {
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    },
    [imagePreviewUrl],
  );

  React.useEffect(() => {
    if (!isInitializing && !isLoggedIn) {
      router.replace("/");
    }
  }, [isInitializing, isLoggedIn, router]);

  const runAuthenticated = React.useCallback(
    async <T,>(request: (token: string) => Promise<T>): Promise<T> => {
      if (!accessToken) throw new Error("로그인이 필요해요.");

      try {
        return await request(accessToken);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;

        const refreshedToken = await refreshAccessToken();
        if (!refreshedToken) {
          logout();
          router.replace("/");
          throw new Error("로그인이 만료되었어요. 다시 로그인해 주세요.");
        }

        const refreshedUser = await fetchAuthUser(refreshedToken);
        setSession(refreshedToken, refreshedUser);
        return request(refreshedToken);
      }
    },
    [accessToken, logout, router, setSession],
  );

  const loadProfile = React.useCallback(async () => {
    if (isInitializing || !isLoggedIn || !accessToken) return;

    setIsLoadingProfile(true);
    setProfileError(null);
    try {
      const loadedProfile = await runAuthenticated(getProfile);
      setProfile(loadedProfile);
      setDraft(profileToDraft(loadedProfile));
    } catch (error) {
      setProfileError(
        error instanceof Error ? error.message : "프로필을 불러오지 못했어요.",
      );
    } finally {
      setIsLoadingProfile(false);
    }
  }, [accessToken, isInitializing, isLoggedIn, runAuthenticated]);

  React.useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadProfile();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadProfile]);

  if (isInitializing || !isLoggedIn || !user) {
    return null;
  }

  async function handleLogout() {
    setProfileError(null);
    try {
      await runAuthenticated(requestLogout);
      logout();
      router.replace("/");
    } catch (error) {
      setProfileError(
        error instanceof Error ? error.message : "로그아웃에 실패했어요.",
      );
    }
  }

  async function handleWithdraw() {
    setIsWithdrawing(true);
    setProfileError(null);
    try {
      await runAuthenticated(deleteAccount);
      setShowWithdraw(false);
      logout();
      router.replace("/");
    } catch (error) {
      setProfileError(
        error instanceof Error ? error.message : "회원 탈퇴에 실패했어요.",
      );
    } finally {
      setIsWithdrawing(false);
    }
  }

  function validateDraft(): boolean {
    const nickname = draft.nickname.trim();
    let isValid = true;

    setNicknameError(undefined);
    setAgeError(undefined);
    if (!nickname) {
      setNicknameError("닉네임을 입력해 주세요.");
      isValid = false;
    } else if (nickname.length > 30) {
      setNicknameError("닉네임은 30자 이하여야 해요.");
      isValid = false;
    }

    if (
      draft.age !== "" &&
      (!Number.isInteger(draft.age) || draft.age < 1 || draft.age > 120)
    ) {
      setAgeError("나이는 1세부터 120세 사이여야 해요.");
      isValid = false;
    }
    return isValid;
  }

  async function handleSave() {
    if (!profile || !validateDraft()) return;

    setIsSaving(true);
    setProfileError(null);
    setImageError(undefined);
    setImageStatusMessage(undefined);
    setStatusMessage(undefined);
    try {
      let updatedProfile = await runAuthenticated((token) =>
        updateUserProfile(token, {
          nickname: draft.nickname.trim(),
          gender: mapGenderToApi(draft.gender),
          birthYear:
            draft.age === "" ? null : new Date().getFullYear() - draft.age,
        }),
      );

      if (selectedImage) {
        setImageUploadStep("requesting-url");
        updatedProfile = await runAuthenticated((token) =>
          uploadProfileImage(token, selectedImage, setImageUploadStep),
        );
      }

      setProfile(updatedProfile);
      setDraft(profileToDraft(updatedProfile));
      const authProfile = mapProfile(updatedProfile);
      updateAuthProfile({
        nickname: authProfile.nickname,
        gender: authProfile.gender,
        birthYear: authProfile.birthYear,
        profileImageUrl: authProfile.profileImageUrl,
      });
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
      setImagePreviewUrl(undefined);
      setSelectedImage(null);
      setStatusMessage("프로필을 저장했어요.");
    } catch (error) {
      if (error instanceof ProfileImageUploadError) {
        setImageError(error.message);
      } else if (error instanceof ApiError && error.code === "CONFLICT") {
        setNicknameError(error.message);
      } else if (error instanceof ApiError && error.fieldErrors) {
        for (const fieldError of error.fieldErrors) {
          if (fieldError.field === "nickname") setNicknameError(fieldError.reason);
          if (fieldError.field === "birthYear") setAgeError(fieldError.reason);
        }
      } else {
        setProfileError(
          error instanceof Error ? error.message : "프로필 저장에 실패했어요.",
        );
      }
    } finally {
      setIsSaving(false);
      setImageUploadStep(undefined);
    }
  }

  function handleImageSelect(file: File | null) {
    setImageError(undefined);
    setImageStatusMessage(undefined);

    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setImagePreviewUrl(undefined);
    setSelectedImage(null);

    if (!file) return;

    try {
      validateProfileImage(file);
      setSelectedImage(file);
      setImagePreviewUrl(URL.createObjectURL(file));
    } catch (error) {
      setImageError(
        error instanceof Error ? error.message : "이미지를 확인하지 못했어요.",
      );
    }
  }

  const savingLabel =
    imageUploadStep === "requesting-url"
      ? "저장 중..."
      : imageUploadStep === "uploading"
        ? "저장 중..."
        : imageUploadStep === "completing"
          ? "저장 중..."
          : undefined;

  const hasProfileChanges =
    profile !== null &&
    (draft.nickname.trim() !== (profile.nickname ?? profile.name ?? "") ||
      draft.gender !== mapGenderToForm(profile.gender) ||
      draft.age !== profileToDraft(profile).age ||
      selectedImage !== null);

  return (
    <MyPageLayout
      tabs={TABS}
      activeTab={tab}
      onTabChange={(key) => setTab(key as MypageTab)}
    >
      {tab === "profile" ? (
        <>
          <h1 className="mb-5 text-xl font-bold text-foreground">프로필수정</h1>
          {isLoadingProfile ? (
            <p className="mb-5 text-sm text-muted-foreground">프로필을 불러오는 중...</p>
          ) : profileError && !profile ? (
            <div className="mb-5 flex items-center justify-between gap-3" role="alert">
              <p className="text-sm text-destructive">{profileError}</p>
              <Button variant="outline" onClick={() => void loadProfile()}>
                다시 시도
              </Button>
            </div>
          ) : (
            <ProfileSection
              nickname={draft.nickname}
              onNicknameChange={(nickname) => {
                setDraft((current) => ({ ...current, nickname }));
                setNicknameError(undefined);
                setStatusMessage(undefined);
              }}
              gender={draft.gender}
              onGenderChange={(gender) => {
                setDraft((current) => ({ ...current, gender }));
                setStatusMessage(undefined);
              }}
              age={draft.age}
              onAgeChange={(value) => {
                setDraft((current) => ({
                  ...current,
                  age: value === "" ? "" : Number(value),
                }));
                setAgeError(undefined);
                setStatusMessage(undefined);
              }}
              avatarSrc={profile?.profileImageUrl ?? undefined}
              avatarColor={user.avatarColor}
              imagePreviewSrc={imagePreviewUrl}
              imageError={imageError}
              imageStatusMessage={imageStatusMessage}
              onImageSelect={handleImageSelect}
              nicknameError={nicknameError}
              ageError={ageError}
              statusMessage={savingLabel ?? statusMessage}
              isSaving={isSaving}
              hasChanges={hasProfileChanges}
              onSave={() => void handleSave()}
              className="mb-5 rounded-xl bg-card p-5 shadow-card"
            />
          )}
          {profileError && profile && (
            <p role="alert" className="mb-3 text-sm text-destructive">
              {profileError}
            </p>
          )}
          <Button variant="outline" className="mb-2 w-full" onClick={handleLogout}>
            로그아웃
          </Button>
          <Button variant="outline" className="w-full text-destructive" onClick={() => setShowWithdraw(true)}>
            회원 탈퇴
          </Button>

          <ConfirmDialog
            open={showWithdraw}
            onOpenChange={setShowWithdraw}
            title="정말 탈퇴하시겠어요?"
            description="계정과 생성한 여행일정이 모두 삭제되며 되돌릴 수 없습니다. 탈퇴 후에는 같은 소셜 계정으로 다시 가입할 수 없어요."
            confirmLabel="탈퇴하기"
            destructive
            isConfirming={isWithdrawing}
            onConfirm={handleWithdraw}
          />
        </>
      ) : (
        <>
          <h1 className="mb-5 text-xl font-bold text-foreground">초대알림</h1>
          <NotificationList
            notifications={notifications}
            onAccept={acceptNotification}
            onReject={rejectNotification}
          />
        </>
      )}
    </MyPageLayout>
  );
}
