"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Pencil, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { Icon } from "@/components/atoms/Icon";
import { Avatar, AvatarImage, AvatarFallback } from "@/components/atoms/Avatar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { CalendarPopover } from "@/components/organisms/CalendarPopover";
import { MapPanel } from "@/components/organisms/MapPanel";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import { PlaceModal, type PlaceSearchResultOption } from "@/components/organisms/PlaceModal";
import { InviteDialog } from "@/components/organisms/InviteDialog";
import { ParticipantManageDialog, type Participant } from "@/components/organisms/ParticipantManageDialog";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { TripDetailPageSkeleton } from "@/components/templates/TripDetailPageSkeleton";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { toPermission, type TravelRole } from "@/lib/api/permission";

import { COMPANION_OPTIONS, UUID_PATTERN, getDateTabs } from "./utils";
import { useTripEditor } from "./useTripEditor";
import { usePlaceEditor } from "./usePlaceEditor";
import { useMapPoints } from "./useMapPoints";

export default function TripDetailPage() {
  return (
    <React.Suspense fallback={null}>
      <TripDetailContent />
    </React.Suspense>
  );
}

function TripDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? undefined;
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

  // detail이 아직 안 불려왔을 수도 있어(초기 로딩 중) 안전한 기본값을 씀 — 아래
  // 훅들은 조건 없이 매번 호출돼야 해서(Rules of Hooks), null 가드보다 앞에 와야 한다.
  const dateTabs = getDateTabs(dateRange.start, dateRange.end);
  const timelineItems = draftTimelineItems ?? detail?.timelineItems ?? [];

  const {
    editingPlace,
    addingPlace,
    setAddingPlace,
    placeDraftName,
    setPlaceDraftName,
    placeDraftNote,
    setPlaceDraftNote,
    placeDraftCategory,
    setPlaceDraftCategory,
    placeDraftFoodSubcategory,
    setPlaceDraftFoodSubcategory,
    placeQuery,
    setPlaceQuery,
    placeResults,
    placeSearchLoading,
    placeSearchError,
    clearPlaceSearch,
    searchNearbyFromMapCenter,
    setEditingPlace,
    setSelectedGooglePlaceId,
    setSelectedPlaceCoords,
    draftPlaceCoords,
    openEditPlace,
    openAddPlace,
    savePlaceModal,
    handleSelectDateChip,
    handleCancelItem,
    handleDeleteItem,
    dateChips,
  } = usePlaceEditor({
    accessToken,
    countries,
    selectedCountryId,
    selectedCityId,
    dateTabs,
    timelineItems,
    setDraftTimelineItems,
  });

  // 여행 기간을 편집해서 날짜 탭 개수가 줄어들면, 이미 골라둔 activeDay가 범위 밖으로
  // 밀려나 탭이 하나도 선택 안 된 것처럼 보이고 일정 목록도 텅 비는 문제가 있었다 —
  // useEffect로 나중에 되돌리는 대신, 렌더링 시점에 바로 유효한 값으로 보정해서 쓴다.
  const visibleActiveDay = Number(activeDay) < dateTabs.length ? activeDay : "0";

  const activeDayNumber = Number(visibleActiveDay) + 1;
  const mapPoints = useMapPoints(accessToken, id, activeDayNumber, detail?.timelineItems);

React.useEffect(() => {
  if (!isInitializing && !isLoggedIn) router.replace("/");
}, [isInitializing, isLoggedIn, router]);

React.useEffect(() => {
    if (!id || !UUID_PATTERN.test(id)) router.replace("/403");
}, [id, router]);

  if (isInitializing || !isLoggedIn || !user) return null;
  if (!detail) return <TripDetailPageSkeleton />;

  // 일정(할일) 관련 조작도 상단 "정보 수정"(연필) 모드일 때만 가능하다 — 페이지 전체가 하나의 조회/수정 스위치를 공유한다.
  const canEditSchedule = canEditInfo && isEditingInfo;
  const selectedCountryName = countries.find((c) => c.countryId === selectedCountryId)?.nameKo ?? "나라 미지정";
  const selectedCityName = cities.find((c) => c.cityId === selectedCityId)?.nameKo ?? "도시 미지정";
  const activeDayItems = timelineItems
    .filter((t) => t.dayNumber === activeDayNumber)
    .sort((a, b) => a.visitOrder - b.visitOrder)
    .map((t) => ({ id: t.timelineItemId, placeName: t.name, note: t.memo || undefined }));
  const unassignedPlaces = timelineItems
    .filter((t) => t.dayNumber === null)
    .sort((a, b) => a.visitOrder - b.visitOrder)
    .map((t) => ({ id: t.timelineItemId, name: t.name, note: t.memo || undefined }));
  // mapPoints는 activeDayNumber에 배정되고 googlePlaceId가 연결된 항목만 좌표가 나온다.
  // 미배정이거나 장소 검색으로 연결 안 된 항목은 지도에 안 찍힌다(경로 아이콘도 없음).
  const savedMarkers = mapPoints.map((p) => ({ id: p.timelineItemId, name: p.name, lat: p.latitude, lng: p.longitude }));
  // 아직 "저장" 전인 신규 항목도, 장소 검색으로 좌표를 이미 아는 경우 활성 날짜에 배정되는
  // 즉시 미리보기 마커로 보여준다(savedMarkers엔 저장 전이라 안 잡힘).
  const draftMarkers = timelineItems
    .filter((t) => (t.dayNumber === activeDayNumber || t.dayNumber === null) && draftPlaceCoords[t.timelineItemId])
    .map((t) => ({
      id: t.timelineItemId,
      name: t.name,
      lat: draftPlaceCoords[t.timelineItemId].lat,
      lng: draftPlaceCoords[t.timelineItemId].lng,
    }));
  const nearbyMarkers = !addingPlace
    ? placeResults.map((place) => ({
        id: `nearby:${place.placeId}`,
        name: place.name,
        lat: place.latitude,
        lng: place.longitude,
      }))
    : [];

  const mapMarkers = [...savedMarkers, ...draftMarkers, ...nearbyMarkers];

  function handleMapMarkerClick(id: string) {
    if (id.startsWith("nearby:")) {
      const placeId = id.slice("nearby:".length);
      const place = placeResults.find((result) => result.placeId === placeId);

      if (!place) return;

      setEditingPlace(null);
      setAddingPlace(true);
      setPlaceDraftName(place.name);
      setSelectedGooglePlaceId(place.placeId);
      setSelectedPlaceCoords({
        lat: place.latitude,
        lng: place.longitude,
      });

      clearPlaceSearch();
      return;
    }

    openEditPlace(id);
  }

  // 드래그로 바뀐 카드 순서를 draft에 반영한다. dnd-kit이 알려주는 건 활성 날짜 카드들의 새 id 순서뿐이라,
  // 그 날짜(dayNumber) 항목의 visitOrder만 1..n으로 다시 매기고 다른 날짜 항목은 그대로 둔다.
  // "정보 수정" 모드에서만 호출되며(readOnly={!canEditSchedule}), 실제 서버 반영은 기존 "저장" 흐름(commitTimelineItemChanges)이 처리한다.
  function handleReorderDay(orderedIds: string[]) {
    const orderIndex = new Map(orderedIds.map((itemId, i) => [itemId, i + 1]));
    setDraftTimelineItems(
      timelineItems.map((item) =>
        item.dayNumber === activeDayNumber && orderIndex.has(item.timelineItemId)
          ? { ...item, visitOrder: orderIndex.get(item.timelineItemId)! }
          : item
      )
    );
  }

  const manageableParticipants: Participant[] = travelMembers
    .filter((m) => !m.isOwner)
    .map((m) => ({
      id: m.userId,
      name: m.nickname ?? "알 수 없음",
      permission: toPermission(m.role as TravelRole),
      status: m.status === "PENDING" ? "pending" : "accepted",
    }));

  return (
    <>
      <DetailLayout
      detailHeader={
        <div className="flex flex-col gap-5">
          <button
            type="button"
            onClick={() => router.push("/trips")}
            className="self-start cursor-pointer text-sm font-bold text-primary"
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
                        <button type="button" title="저장" className="cursor-pointer text-primary" onClick={saveEditInfo}>
                          <Icon icon={Check} size="sm" aria-label="저장" />
                        </button>
                        <button type="button" title="취소" className="cursor-pointer text-muted-foreground" onClick={cancelEditInfo}>
                          <Icon icon={X} size="sm" aria-label="취소" />
                        </button>
                      </>
                    ) : (
                      <>
                        <button type="button" title="정보 수정" className="cursor-pointer text-muted-foreground" onClick={startEditInfo}>
                          <Icon icon={Pencil} size="sm" aria-label="정보 수정" />
                        </button>
                        {isOwner && (
                          <button type="button" title="여행일정 삭제" className="cursor-pointer text-destructive" onClick={() => setShowDeleteConfirm(true)}>
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
                {travelMembers
                  .filter((m) => m.status === "ACCEPTED")
                  .map((m, i) => (
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
                className="flex cursor-pointer items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold text-foreground hover:bg-muted"
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
            activeDay={visibleActiveDay}
            onDayChange={setActiveDay}
            items={activeDayItems}
            unassigned={unassignedPlaces}
            map={
              <MapPanel
                markers={mapMarkers}
                onMarkerClick={handleMapMarkerClick}
                onSearchNearby={canEditSchedule ? searchNearbyFromMapCenter : undefined}
                nearbySearchDisabled={placeSearchLoading}
              />
            }
            readOnly={!canEditSchedule}
            onOpenItem={openEditPlace}
            onEditItem={openEditPlace}
            onCancelItem={handleCancelItem}
            onDeleteItem={handleDeleteItem}
            onAssignPlace={openEditPlace}
            onReorderItems={handleReorderDay}
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
            clearPlaceSearch();
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
        placeSearchLoading={placeSearchLoading}
        placeSearchError={placeSearchError}
        placeResults={placeResults.map(
          (r): PlaceSearchResultOption => ({
            placeId: r.placeId,
            name: r.name,
            latitude: r.latitude,
            longitude: r.longitude,
          })
        )}
        onSelectPlaceResult={(result) => {
          setPlaceDraftName(result.name);
          setSelectedGooglePlaceId(result.placeId);
          setSelectedPlaceCoords({ lat: result.latitude, lng: result.longitude });
          clearPlaceSearch();
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
