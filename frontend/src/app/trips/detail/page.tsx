"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/atoms/Button";
import { Textarea } from "@/components/atoms/Textarea";
import { MapPanel } from "@/components/organisms/MapPanel";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import { PlaceModal, type PlaceSearchResultOption } from "@/components/organisms/PlaceModal";
import { InviteDialog } from "@/components/organisms/InviteDialog";
import { ParticipantManageDialog, type Participant } from "@/components/organisms/ParticipantManageDialog";
import { TripDetailHeader } from "@/components/organisms/TripDetailHeader";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { TripDetailPageSkeleton } from "@/components/templates/TripDetailPageSkeleton";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { toPermission, type TravelRole } from "@/lib/api/permission";
import { DESCRIPTION_MAX_LENGTH } from "@/lib/validation/text";

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
    placeNameError,
    setPlaceNameError,
    placeDraftNote,
    setPlaceDraftNote,
    placeDraftCategory,
    setPlaceDraftCategory,
    placeDraftFoodSubcategory,
    setPlaceDraftFoodSubcategory,
    placeQuery,
    setPlaceQuery,
    placeResults,
    setPlaceResults,
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
    .filter((t) => t.dayNumber === activeDayNumber && draftPlaceCoords[t.timelineItemId])
    .map((t) => ({
      id: t.timelineItemId,
      name: t.name,
      lat: draftPlaceCoords[t.timelineItemId].lat,
      lng: draftPlaceCoords[t.timelineItemId].lng,
    }));
  const mapMarkers = [...savedMarkers, ...draftMarkers];

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
        <TripDetailHeader
          onBack={() => router.push("/trips")}
          title={detail.title}
          isEditing={isEditingInfo}
          titleDraft={titleDraft}
          onTitleDraftChange={setTitleDraft}
          canEdit={canEditInfo}
          onStartEdit={startEditInfo}
          onSaveEdit={saveEditInfo}
          onCancelEdit={cancelEditInfo}
          saveError={infoSaveError}
          isOwner={isOwner}
          onDeleteClick={() => setShowDeleteConfirm(true)}
          members={travelMembers}
          onInviteClick={() => setShowInvite(true)}
          onManageClick={() => setShowManage(true)}
          onLeaveClick={() => setShowLeaveConfirm(true)}
          countries={countries}
          selectedCountryId={selectedCountryId}
          onCountryChange={handleCountryChangeDraft}
          cities={cities}
          selectedCityId={selectedCityId}
          onCityChange={(v) => setSelectedCityId(Number(v))}
          selectedCountryName={selectedCountryName}
          selectedCityName={selectedCityName}
          dateRange={dateRange}
          onDateRangeChange={setDateRange}
          showCalendar={showCalendar}
          onToggleCalendar={() => setShowCalendar((v) => !v)}
          onApplyCalendar={() => setShowCalendar(false)}
          companion={companion}
          onCompanionChange={setCompanion}
          companionOptions={COMPANION_OPTIONS}
        />
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
            map={<MapPanel markers={mapMarkers} onMarkerClick={openEditPlace} />}
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
              <div>
                <Textarea
                  placeholder="이번 여행에 대해 간단히 소개해보세요"
                  value={description}
                  maxLength={DESCRIPTION_MAX_LENGTH}
                  onChange={(e) => setDescription(e.target.value)}
                  className="h-[90px]"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {description.length}/{DESCRIPTION_MAX_LENGTH}
                </p>
              </div>
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
        onNameChange={(value) => {
          setPlaceDraftName(value);
          setPlaceNameError(null);
        }}
        nameError={placeNameError}
        note={placeDraftNote}
        onNoteChange={setPlaceDraftNote}
        category={placeDraftCategory}
        onCategoryChange={setPlaceDraftCategory}
        foodSubcategory={placeDraftFoodSubcategory}
        onFoodSubcategoryChange={setPlaceDraftFoodSubcategory}
        placeQuery={placeQuery}
        onPlaceQueryChange={setPlaceQuery}
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
          setPlaceNameError(null);
          setSelectedGooglePlaceId(result.placeId);
          setSelectedPlaceCoords({ lat: result.latitude, lng: result.longitude });
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
