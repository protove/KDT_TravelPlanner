"use client";

import * as React from "react";
import { useRouter, useParams } from "next/navigation";
import { Pencil, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { Icon } from "@/components/atoms/Icon";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/atoms/Avatar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { AppHeader } from "@/components/organisms/AppHeader";
import { CalendarPopover } from "@/components/organisms/CalendarPopover";
import { MapPanel } from "@/components/organisms/MapPanel";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import {
  PlaceModal,
  type PlaceDateChip,
  type PlaceSearchResultOption,
  type TimelineCategoryOption,
} from "@/components/organisms/PlaceModal";
import { InviteDialog } from "@/components/organisms/InviteDialog";
import { ParticipantManageDialog, type Participant } from "@/components/organisms/ParticipantManageDialog";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import type { Permission } from "@/components/molecules/PermissionSelect";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { type TimelineItem } from "@/lib/api/travel";
import { toPermission, type TravelRole } from "@/lib/api/permission";
import { searchPlaces, type PlaceSearchResult } from "@/lib/api/places";

import {
  COMPANION_OPTIONS,
  UUID_PATTERN,
  NEW_ITEM_PREFIX,
  formatIsoDate,
  pseudoMapPosition,
  computeNextVisitOrder,
  getDateTabs,
} from "./utils";
import { useTripEditor } from "./useTripEditor";

export default function TripDetailPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);

  const {
    detail,
    dateRange,
    setDateRange,
    companion,
    setCompanion,
    countries,
    cities,
    selectedCountryId,
    setSelectedCityId,
    selectedCityId,
    description,
    setDescription,
    isEditingInfo,
    titleDraft,
    setTitleDraft,
    infoSaveError,
    draftTimelineItems,
    setDraftTimelineItems,
    travelMembers,
    inviteNickname,
    setInviteNickname,
    invitePermission,
    setInvitePermission,
    inviteError,
    setInviteError,
    handleMemberPermissionChange,
    handleRemoveMember,
    handleInvite,
    handleLeaveTravel,
    handleDeleteTravel,
    handleCountryChangeDraft,
    startEditInfo,
    cancelEditInfo,
    saveEditInfo,
    isOwner,
    canEditInfo,
  } = useTripEditor(id, accessToken, router);

  const [activeDay, setActiveDay] = React.useState("0");
  const [showCalendar, setShowCalendar] = React.useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = React.useState(false);
  const [showLeaveConfirm, setShowLeaveConfirm] = React.useState(false);
  const [showInvite, setShowInvite] = React.useState(false);
  const [showManage, setShowManage] = React.useState(false);

  const [editingPlace, setEditingPlace] = React.useState<TimelineItem | null>(null);
  const [addingPlace, setAddingPlace] = React.useState(false);
  const [placeDraftName, setPlaceDraftName] = React.useState("");
  const [placeDraftNote, setPlaceDraftNote] = React.useState("");
  const [placeDraftCategory, setPlaceDraftCategory] = React.useState<TimelineCategoryOption>("관광지");
  const [placeDraftFoodSubcategory, setPlaceDraftFoodSubcategory] = React.useState("");
  const [placeDraftDayNumbers, setPlaceDraftDayNumbers] = React.useState<number[]>([]);
  const [placeQuery, setPlaceQuery] = React.useState("");
  const [placeResults, setPlaceResults] = React.useState<PlaceSearchResult[]>([]);
  const [selectedGooglePlaceId, setSelectedGooglePlaceId] = React.useState<string | null>(null);

  React.useEffect(() => {
    const countryCode = countries.find((c) => c.countryId === selectedCountryId)?.code;
    if (!accessToken || !placeQuery.trim() || !countryCode) return;
    const handle = setTimeout(() => {
      searchPlaces(accessToken, placeQuery.trim(), countryCode).then(setPlaceResults).catch(() => {});
    }, 300);
    return () => clearTimeout(handle);
  }, [accessToken, placeQuery, countries, selectedCountryId]);

React.useEffect(() => {
  if (!isInitializing && !isLoggedIn) router.replace("/landing");
}, [isInitializing, isLoggedIn, router]);

React.useEffect(() => {
  if (id && !UUID_PATTERN.test(id)) router.replace("/403");
}, [id, router]);

  if (isInitializing || !isLoggedIn || !user || !detail) return null;

  const dateTabs = getDateTabs(dateRange.start, dateRange.end);
  const activeDayNumber = Number(activeDay) + 1;
  // 일정(할일) 관련 조작도 상단 "정보 수정"(연필) 모드일 때만 가능하다 — 페이지 전체가 하나의 조회/수정 스위치를 공유한다.
  const canEditSchedule = canEditInfo && isEditingInfo;
  const selectedCountryName = countries.find((c) => c.countryId === selectedCountryId)?.nameKo ?? "나라 미지정";
  const selectedCityName = cities.find((c) => c.cityId === selectedCityId)?.nameKo ?? "도시 미지정";
  // 정보 수정 중이면 로컬 draft를, 아니면 서버 원본을 화면에 그대로 보여준다.
  const timelineItems = draftTimelineItems ?? detail.timelineItems;
  const activeDayItems = timelineItems
    .filter((t) => t.dayNumber === activeDayNumber)
    .sort((a, b) => a.visitOrder - b.visitOrder)
    .map((t) => ({ id: t.timelineItemId, placeName: t.name, note: t.memo || undefined }));
  const unassignedPlaces = timelineItems
    .filter((t) => t.dayNumber === null)
    .sort((a, b) => a.visitOrder - b.visitOrder)
    .map((t) => ({ id: t.timelineItemId, name: t.name, note: t.memo || undefined }));
  const mapMarkers = timelineItems.map((t) => ({
    id: t.timelineItemId,
    name: t.name,
    ...pseudoMapPosition(t.timelineItemId),
  }));

  const manageableParticipants: Participant[] = travelMembers
    .filter((m) => !m.isOwner)
    .map((m) => ({
      id: m.userId,
      name: m.nickname ?? "알 수 없음",
      permission: toPermission(m.role as TravelRole),
      status: "accepted",
    }));

  function openEditPlace(itemId: string) {
    const item = timelineItems.find((t) => t.timelineItemId === itemId);
    if (!item) return;
    setEditingPlace(item);
    setPlaceDraftNote(item.memo ?? "");
    setPlaceDraftCategory(item.category);
    setPlaceDraftFoodSubcategory(item.foodSubcategory ?? "");
    setPlaceDraftDayNumbers(item.dayNumber != null ? [item.dayNumber] : []);
  }

  function openAddPlace() {
    setAddingPlace(true);
    setPlaceDraftName("");
    setPlaceDraftNote("");
    setPlaceDraftCategory("관광지");
    setPlaceDraftFoodSubcategory("");
    setPlaceDraftDayNumbers([]);
    setPlaceQuery("");
    setPlaceResults([]);
    setSelectedGooglePlaceId(null);
  }

  // 전부 로컬 draft(draftTimelineItems)만 바꾼다 — 실제 서버 반영은 상단 "저장"을 눌러야 일어난다.
  function savePlaceModal() {
    if (editingPlace) {
      const [primaryDay, ...extraDays] = [...placeDraftDayNumbers].sort((a, b) => a - b);
      const resolvedPrimaryDay = primaryDay ?? null;
      const visitDate = resolvedPrimaryDay != null ? formatIsoDate(dateTabs[resolvedPrimaryDay - 1].date) : null;
      setDraftTimelineItems((prev) => {
        const base = prev ?? [];
        const updated = base.map((item) =>
          item.timelineItemId === editingPlace.timelineItemId
            ? {
                ...item,
                category: placeDraftCategory,
                foodSubcategory: placeDraftCategory === "음식" ? placeDraftFoodSubcategory || null : null,
                memo: placeDraftNote || null,
                dayNumber: resolvedPrimaryDay,
                visitDate,
                visitOrder:
                  resolvedPrimaryDay !== editingPlace.dayNumber
                    ? computeNextVisitOrder(base, resolvedPrimaryDay)
                    : item.visitOrder,
              }
            : item
        );
        // 같은 장소를 여러 날짜에 배정하면, 첫 날짜는 원본에 반영하고 나머지 날짜는 같은 내용으로 복제한다.
        const clones: TimelineItem[] = extraDays.map((day) => ({
          timelineItemId: `${NEW_ITEM_PREFIX}${crypto.randomUUID()}`,
          dayNumber: day,
          visitDate: formatIsoDate(dateTabs[day - 1].date),
          cityId: editingPlace.cityId,
          category: placeDraftCategory,
          foodSubcategory: placeDraftCategory === "음식" ? placeDraftFoodSubcategory || null : null,
          name: editingPlace.name,
          googlePlaceId: editingPlace.googlePlaceId,
          visitOrder: computeNextVisitOrder(base, day),
          memo: placeDraftNote || null,
        }));
        return [...updated, ...clones];
      });
      setEditingPlace(null);
    } else if (addingPlace) {
      const name = placeDraftName.trim();
      if (!name) return;
      setDraftTimelineItems((prev) => {
        const base = prev ?? [];
        const newItem: TimelineItem = {
          timelineItemId: `${NEW_ITEM_PREFIX}${crypto.randomUUID()}`,
          dayNumber: null,
          visitDate: null,
          cityId: selectedCityId,
          category: placeDraftCategory,
          foodSubcategory: placeDraftCategory === "음식" ? placeDraftFoodSubcategory || null : null,
          name,
          googlePlaceId: selectedGooglePlaceId,
          visitOrder: computeNextVisitOrder(base, null),
          memo: placeDraftNote || null,
        };
        return [...base, newItem];
      });
      setAddingPlace(false);
    }
  }

  function handleSelectDateChip(i: number) {
    const dayNumber = Number(dateTabs[i].key) + 1;
    setPlaceDraftDayNumbers((prev) =>
      prev.includes(dayNumber) ? prev.filter((d) => d !== dayNumber) : [...prev, dayNumber]
    );
  }

  function handleCancelItem(itemId: string) {
    setDraftTimelineItems((prev) => {
      if (!prev) return prev;
      return prev.map((item) =>
        item.timelineItemId === itemId
          ? { ...item, dayNumber: null, visitDate: null, visitOrder: computeNextVisitOrder(prev, null) }
          : item
      );
    });
  }

  function handleDeleteItem(itemId: string) {
    setDraftTimelineItems((prev) => (prev ? prev.filter((item) => item.timelineItemId !== itemId) : prev));
  }

  const dateChips: PlaceDateChip[] = dateTabs.map((tab) => ({
    label: `${tab.date.getMonth() + 1}.${tab.date.getDate()}`,
    selected: placeDraftDayNumbers.includes(Number(tab.key) + 1),
  }));

  return (
    <>
      <DetailLayout
      header={<AppHeader loggedIn userInitial={user.initial} avatarColor={user.avatarColor} onLogoClick={() => router.push("/trips")} onProfileClick={() => router.push("/mypage")} onNotificationClick={() => router.push("/notifications")} />}
      detailHeader={
        <div className="flex flex-col gap-5">
          <button
            type="button"
            onClick={() => router.push("/trips")}
            className="self-start text-sm font-bold text-primary"
          >
            ← 여행일정 목록
          </button>

          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                {isEditingInfo ? (
                  <Input
                    autoFocus
                    value={titleDraft}
                    onChange={(e) => setTitleDraft(e.target.value)}
                    className="h-auto w-auto text-2xl font-bold"
                  />
                ) : (
                  <h1 className="text-2xl font-bold text-foreground">{detail.title}</h1>
                )}
                {canEditInfo && (
                  <>
                    {isEditingInfo ? (
                      <>
                        <button type="button" title="저장" className="text-primary" onClick={saveEditInfo}>
                          <Icon icon={Check} size="sm" aria-label="저장" />
                        </button>
                        <button type="button" title="취소" className="text-muted-foreground" onClick={cancelEditInfo}>
                          <Icon icon={X} size="sm" aria-label="취소" />
                        </button>
                      </>
                    ) : (
                      <>
                        <button type="button" title="정보 수정" className="text-muted-foreground" onClick={startEditInfo}>
                          <Icon icon={Pencil} size="sm" aria-label="정보 수정" />
                        </button>
                        {isOwner && (
                          <button type="button" title="여행일정 삭제" className="text-destructive" onClick={() => setShowDeleteConfirm(true)}>
                            <Icon icon={Trash2} size="sm" aria-label="여행일정 삭제" />
                          </button>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
              {infoSaveError && <p className="mt-1 text-xs text-destructive">{infoSaveError}</p>}
              <div className="mt-1.5 flex">
                {travelMembers.map((m, i) => (
                  <Avatar
                    key={m.userId}
                    className="h-[22px] w-[22px]"
                    style={i > 0 ? { marginLeft: "-6px" } : undefined}
                  >
                    {m.profileImageUrl && <AvatarImage src={m.profileImageUrl} alt={m.nickname ?? ""} />}
                    <AvatarFallback className="text-[10px]">{(m.nickname ?? "?").slice(0, 1)}</AvatarFallback>
                  </Avatar>
                ))}
              </div>
            </div>

            {isOwner ? (
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => setShowInvite(true)}>
                  참여자 초대
                </Button>
                <Button onClick={() => setShowManage(true)}>참여자 관리</Button>
              </div>
            ) : (
              <Button variant="outline" onClick={() => setShowLeaveConfirm(true)}>
                나가기
              </Button>
            )}
          </div>

          {isEditingInfo ? (
            <div className="relative flex w-fit flex-wrap items-center gap-1 rounded-full bg-card p-1.5 shadow-card">
              <div className="flex items-center gap-1.5 px-2.5 py-1.5">
                <span>📍</span>
                <Select
                  value={selectedCountryId != null ? String(selectedCountryId) : undefined}
                  onValueChange={handleCountryChangeDraft}
                >
                  <SelectTrigger className="h-auto w-auto gap-1 border-none bg-transparent px-0.5 py-0.5 text-sm font-bold shadow-none">
                    <SelectValue placeholder="나라" />
                  </SelectTrigger>
                  <SelectContent>
                    {countries.map((c) => (
                      <SelectItem key={c.countryId} value={String(c.countryId)}>
                        {c.nameKo}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-border-strong">·</span>
                <Select
                  value={selectedCityId != null ? String(selectedCityId) : undefined}
                  onValueChange={(v) => setSelectedCityId(Number(v))}
                  disabled={selectedCountryId == null}
                >
                  <SelectTrigger className="h-auto w-auto gap-1 border-none bg-transparent px-0.5 py-0.5 text-sm font-bold shadow-none">
                    <SelectValue placeholder="도시" />
                  </SelectTrigger>
                  <SelectContent>
                    {cities.map((c) => (
                      <SelectItem key={c.cityId} value={String(c.cityId)}>
                        {c.nameKo}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="h-5 w-px bg-border" />
              <button
                type="button"
                onClick={() => setShowCalendar((v) => !v)}
                className="flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold text-foreground hover:bg-muted"
              >
                📅 <DateRangeBadge start={dateRange.start} end={dateRange.end} />
              </button>
              <div className="h-5 w-px bg-border" />
              <Select value={companion} onValueChange={setCompanion}>
                <SelectTrigger className="h-auto w-auto gap-1.5 border-none px-3 py-1.5 shadow-none">
                  <span>👥</span>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {COMPANION_OPTIONS.map((opt) => (
                    <SelectItem key={opt} value={opt}>
                      {opt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {showCalendar && (
                <div className="absolute left-0 top-[calc(100%+8px)] z-20">
                  <CalendarPopover
                    value={dateRange}
                    onChange={(range) => setDateRange(range)}
                    onApply={() => setShowCalendar(false)}
                  />
                </div>
              )}
            </div>
          ) : (
            <div className="flex w-fit flex-wrap items-center gap-1 rounded-full bg-card p-1.5 shadow-card">
              <div className="flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-bold text-foreground">
                📍 {selectedCountryName} · {selectedCityName}
              </div>
              <div className="h-5 w-px bg-border" />
              <div className="flex items-center gap-2 px-3.5 py-2 text-sm font-bold text-foreground">
                📅 <DateRangeBadge start={dateRange.start} end={dateRange.end} />
              </div>
              <div className="h-5 w-px bg-border" />
              <div className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-bold text-foreground">
                👥 {companion}
              </div>
            </div>
          )}
        </div>
      }
      schedule={
        <div className="flex flex-col gap-6">
          <div className="text-lg font-bold text-foreground">여행계획</div>
          <ScheduleBoard
            days={dateTabs}
            activeDay={activeDay}
            onDayChange={setActiveDay}
            items={activeDayItems}
            unassigned={unassignedPlaces}
            map={<MapPanel markers={mapMarkers} onMarkerClick={openEditPlace} />}
            readOnly={!canEditSchedule}
            onOpenItem={openEditPlace}
            onEditItem={openEditPlace}
            onCancelItem={handleCancelItem}
            onDeleteItem={handleDeleteItem}
            onAssignPlace={openEditPlace}
          />
          {canEditSchedule && (
            <Button variant="outline" className="w-full border-dashed" onClick={openAddPlace}>
              + 목적지 추가
            </Button>
          )}

          <div>
            <div className="mb-2 text-sm font-bold text-foreground">여행 설명</div>
            {isEditingInfo ? (
              <Textarea
                placeholder="이번 여행에 대해 간단히 소개해보세요"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="h-[90px]"
              />
            ) : (
              <p className="text-sm text-muted-foreground">{description || "이번 여행에 대해 간단히 소개해보세요"}</p>
            )}
          </div>
        </div>
      }
      />

      <PlaceModal
        open={editingPlace != null || addingPlace}
        onOpenChange={(open) => {
          if (!open) {
            setEditingPlace(null);
            setAddingPlace(false);
            setPlaceQuery("");
            setPlaceResults([]);
          }
        }}
        mode={editingPlace ? "edit" : "add"}
        title={editingPlace ? editingPlace.name : "목적지 추가"}
        name={placeDraftName}
        onNameChange={setPlaceDraftName}
        note={placeDraftNote}
        onNoteChange={setPlaceDraftNote}
        category={placeDraftCategory}
        onCategoryChange={setPlaceDraftCategory}
        foodSubcategory={placeDraftFoodSubcategory}
        onFoodSubcategoryChange={setPlaceDraftFoodSubcategory}
        placeQuery={placeQuery}
        onPlaceQueryChange={setPlaceQuery}
        placeResults={placeResults.map((r): PlaceSearchResultOption => ({ placeId: r.placeId, name: r.name }))}
        onSelectPlaceResult={(result) => {
          setPlaceDraftName(result.name);
          setSelectedGooglePlaceId(result.placeId);
          setPlaceQuery("");
          setPlaceResults([]);
        }}
        dateChips={editingPlace ? dateChips : undefined}
        onSelectDateChip={handleSelectDateChip}
        onSave={savePlaceModal}
        readOnly={!canEditSchedule}
      />

      <InviteDialog
        open={showInvite}
        onOpenChange={(open) => {
          setShowInvite(open);
          if (!open) {
            setInviteNickname("");
            setInvitePermission("read");
            setInviteError(null);
          }
        }}
        nickname={inviteNickname}
        onNicknameChange={setInviteNickname}
        permission={invitePermission}
        onPermissionChange={setInvitePermission}
        onInvite={() => handleInvite(() => setShowInvite(false))}
        error={inviteError}
      />

      <ParticipantManageDialog
        open={showManage}
        onOpenChange={setShowManage}
        participants={manageableParticipants}
        onPermissionChange={handleMemberPermissionChange}
        onRemove={handleRemoveMember}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title="여행일정 삭제"
        description="삭제하면 되돌릴 수 없습니다."
        confirmLabel="삭제하기"
        destructive
        onConfirm={handleDeleteTravel}
      />

      <ConfirmDialog
        open={showLeaveConfirm}
        onOpenChange={setShowLeaveConfirm}
        title="일정을 나가시겠어요?"
        description="다시 참여하려면 초대를 받아야 해요."
        confirmLabel="나가기"
        onConfirm={handleLeaveTravel}
      />
    </>
  );
}
