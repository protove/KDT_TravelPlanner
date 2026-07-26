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
import {
  fetchTravelDetail,
  updateTravel,
  deleteTravel,
  type TravelDetail,
  type CompanionType,
  type TimelineItem,
} from "@/lib/api/travel";
import { fetchCountries, fetchCitiesByCountry, type Country, type City } from "@/lib/api/location";
import { fetchTravelMembers, updateMemberRole, removeMember, leaveTravel, type TravelMember } from "@/lib/api/members";
import { createInvitation } from "@/lib/api/invitations";
import { toPermission, toTravelRole, type TravelRole } from "@/lib/api/permission";
import { searchPlaces, type PlaceSearchResult } from "@/lib/api/places";
import { createTimelineItem, updateTimelineItem, deleteTimelineItem } from "@/lib/api/timelineItems";
import { ApiError } from "@/lib/api/client";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

const COMPANION_OPTIONS = ["혼자", "연인과", "가족과", "친구와", "반려동물과", "기타"];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const COMPANION_LABELS: Record<CompanionType, string> = {
  SOLO: "혼자",
  COUPLE: "연인과",
  FAMILY: "가족과",
  FRIEND: "친구와",
  PET: "반려동물과",
  ETC: "기타",
};

const COMPANION_TYPE_BY_LABEL: Record<string, CompanionType> = Object.fromEntries(
  Object.entries(COMPANION_LABELS).map(([type, label]) => [label, type as CompanionType]),
);

function parseIsoDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatIsoDate(date: Date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/**
 * MapPanel은 아직 실제 지도 SDK 없이 x/y 퍼센트로만 마커를 찍는 mock 컴포넌트라
 * (실제 좌표 연동은 별도 프로젝트로 범위 밖), timelineItemId를 해시해 고정된
 * 위치를 만들어준다. 실제 지리적 위치를 의미하지 않는다.
 */
function pseudoMapPosition(timelineItemId: string) {
  let hash = 0;
  for (let i = 0; i < timelineItemId.length; i++) hash = (hash * 31 + timelineItemId.charCodeAt(i)) >>> 0;
  return { x: 15 + (hash % 70), y: 15 + ((hash >>> 8) % 70) };
}

/** "정보 수정" 모드에서 아직 서버에 없는(로컬 draft) 일정 항목에 붙이는 임시 id 접두어. */
const NEW_ITEM_PREFIX = "draft:";

function computeNextVisitOrder(items: TimelineItem[], dayNumber: number | null): number {
  const sameDay = items.filter((t) => t.dayNumber === dayNumber);
  return sameDay.length === 0 ? 1 : Math.max(...sameDay.map((t) => t.visitOrder)) + 1;
}

/** visitDate(실제 날짜)를 기준으로, 주어진 시작일 하에서의 dayNumber(몇 번째 날)를 계산한다. */
function dayNumberForStart(visitDateIso: string, start: Date): number {
  const visitDate = parseIsoDate(visitDateIso);
  const s = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const days = Math.round((visitDate.getTime() - s.getTime()) / (24 * 60 * 60 * 1000));
  return days + 1;
}

/**
 * 여행 기간(시작/종료일)이 바뀔 때, 이미 배정된 모든 항목을 "절대 날짜(visitDate) 고정" 기준으로
 * 다시 정리한다 — 새 기간 안에 있으면 dayNumber만 새 시작일 기준으로 재계산하고, 새 기간 밖으로
 * 벗어나면 미배정(삭제 아님)으로 되돌린다. 이번 편집 세션에서 직접 안 건드린 항목도 포함된다.
 */
function reconcileForDateRange(items: TimelineItem[], newStart: Date, newEnd: Date): TimelineItem[] {
  const start = new Date(newStart.getFullYear(), newStart.getMonth(), newStart.getDate());
  const end = new Date(newEnd.getFullYear(), newEnd.getMonth(), newEnd.getDate());
  return items.map((item) => {
    if (item.dayNumber == null || !item.visitDate) return item;
    const visitDate = parseIsoDate(item.visitDate);
    if (visitDate.getTime() < start.getTime() || visitDate.getTime() > end.getTime()) {
      return { ...item, dayNumber: null, visitDate: null };
    }
    const newDayNumber = dayNumberForStart(item.visitDate, newStart);
    return newDayNumber !== item.dayNumber ? { ...item, dayNumber: newDayNumber } : item;
  });
}

/**
 * UI에서 미리 계산해둔 visitOrder는 이후 편집(날짜 재배정, 다른 항목 추가/삭제 등)을 거치며
 * 서로 어긋날 수 있다. 저장 직전에 날짜별로 기존 순서를 유지한 채 1,2,3...으로 다시 번호를
 * 매겨서, 같은 날짜에 순서가 중복되는 일이 없도록 확정한다.
 */
function normalizeVisitOrders(items: TimelineItem[]): TimelineItem[] {
  const groups = new Map<number, TimelineItem[]>();
  for (const item of items) {
    if (item.dayNumber == null) continue;
    const group = groups.get(item.dayNumber) ?? [];
    group.push(item);
    groups.set(item.dayNumber, group);
  }
  const orderByItem = new Map<TimelineItem, number>();
  for (const group of groups.values()) {
    const sorted = [...group].sort((a, b) => a.visitOrder - b.visitOrder);
    sorted.forEach((item, i) => orderByItem.set(item, i + 1));
  }
  return items.map((item) => {
    const newOrder = orderByItem.get(item);
    return newOrder != null && newOrder !== item.visitOrder ? { ...item, visitOrder: newOrder } : item;
  });
}

function getDateTabs(start: Date, end: Date) {
  const tabs: { key: string; label: string; date: Date }[] = [];
  const cur = new Date(start);
  while (cur <= end) {
    tabs.push({
      key: String(tabs.length),
      label: `${cur.getMonth() + 1}/${cur.getDate()} (${WEEKDAYS[cur.getDay()]})`,
      date: new Date(cur),
    });
    cur.setDate(cur.getDate() + 1);
  }
  return tabs;
}

export default function TripDetailPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [detail, setDetail] = React.useState<TravelDetail | null>(null);
  const [dateRange, setDateRange] = React.useState({ start: new Date(), end: new Date() });
  const [companion, setCompanion] = React.useState(COMPANION_OPTIONS[0]);

  const [countries, setCountries] = React.useState<Country[]>([]);
  const [cities, setCities] = React.useState<City[]>([]);
  const [selectedCountryId, setSelectedCountryId] = React.useState<number | null>(null);
  const [selectedCityId, setSelectedCityId] = React.useState<number | null>(null);
  const [description, setDescription] = React.useState("");
  const [isEditingInfo, setIsEditingInfo] = React.useState(false);
  const [titleDraft, setTitleDraft] = React.useState("");
  const [infoSaveError, setInfoSaveError] = React.useState<string | null>(null);
  // null이면 조회 모드(서버 데이터 그대로 보여줌), 배열이면 "정보 수정" 모드 중 로컬로만 바뀐 draft.
  const [draftTimelineItems, setDraftTimelineItems] = React.useState<TimelineItem[] | null>(null);
  const editSnapshotRef = React.useRef<{
    dateRange: { start: Date; end: Date };
    companion: string;
    countryId: number | null;
    cityId: number | null;
    description: string;
  } | null>(null);

  const [travelMembers, setTravelMembers] = React.useState<TravelMember[]>([]);
  const [inviteNickname, setInviteNickname] = React.useState("");
  const [invitePermission, setInvitePermission] = React.useState<Permission>("read");
  const [inviteError, setInviteError] = React.useState<string | null>(null);

  const refreshDetail = React.useCallback(() => {
    if (!accessToken || !id || !UUID_PATTERN.test(id)) return;
    fetchTravelDetail(accessToken, id)
      .then((res) => {
        setDetail(res);
        setDateRange({ start: parseIsoDate(res.startDate), end: parseIsoDate(res.endDate) });
        setCompanion(res.companionType ? COMPANION_LABELS[res.companionType] : COMPANION_OPTIONS[0]);
        setSelectedCountryId(res.countryId);
        setSelectedCityId(res.cityId);
        setDescription(res.comment ?? "");
      })
      .catch(() => router.replace("/403"));
  }, [accessToken, id, router]);

  React.useEffect(() => {
    refreshDetail();
  }, [refreshDetail]);

  React.useEffect(() => {
    if (!accessToken) return;
    fetchCountries(accessToken).then(setCountries).catch(() => {});
  }, [accessToken]);

  React.useEffect(() => {
    if (!accessToken || selectedCountryId == null) return;
    fetchCitiesByCountry(accessToken, selectedCountryId).then(setCities).catch(() => {});
  }, [accessToken, selectedCountryId]);

  const refreshMembers = React.useCallback(() => {
    if (!accessToken || !id || !UUID_PATTERN.test(id)) return;
    fetchTravelMembers(accessToken, id).then(setTravelMembers).catch(() => {});
  }, [accessToken, id]);

  React.useEffect(() => {
    refreshMembers();
  }, [refreshMembers]);

  async function handleMemberPermissionChange(memberId: string, permission: Permission) {
    if (!accessToken || !id) return;
    try {
      await updateMemberRole(accessToken, id, memberId, toTravelRole(permission));
      refreshMembers();
    } catch (e) {
      console.error("참여자 권한 변경 실패", e);
    }
  }

  async function handleRemoveMember(memberId: string) {
    if (!accessToken || !id) return;
    try {
      await removeMember(accessToken, id, memberId);
      refreshMembers();
    } catch (e) {
      console.error("참여자 추방 실패", e);
    }
  }

  async function handleInvite() {
    if (!accessToken || !id) return;
    setInviteError(null);
    try {
      await createInvitation(accessToken, id, {
        nickname: inviteNickname.trim(),
        role: toTravelRole(invitePermission),
      });
      setInviteNickname("");
      setShowInvite(false);
    } catch (e) {
      setInviteError(e instanceof ApiError ? e.message : "초대에 실패했어요.");
    }
  }

  async function handleLeaveTravel() {
    if (accessToken && id) {
      try {
        await leaveTravel(accessToken, id);
      } catch (e) {
        console.error("여행 나가기 실패", e);
      }
    }
    router.push("/trips");
  }

  async function handleDeleteTravel() {
    if (accessToken && id) {
      try {
        await deleteTravel(accessToken, id);
      } catch (e) {
        console.error("여행 삭제 실패", e);
        return;
      }
    }
    router.push("/trips");
  }

  function handleCountryChangeDraft(value: string) {
    setSelectedCountryId(Number(value));
    setSelectedCityId(null);
    setCities([]);
  }

  function startEditInfo() {
    if (!detail) return;
    editSnapshotRef.current = { dateRange, companion, countryId: selectedCountryId, cityId: selectedCityId, description };
    setTitleDraft(detail.title);
    setDraftTimelineItems(detail.timelineItems);
    setInfoSaveError(null);
    setIsEditingInfo(true);
  }

  function cancelEditInfo() {
    const snap = editSnapshotRef.current;
    if (snap) {
      setDateRange(snap.dateRange);
      setCompanion(snap.companion);
      setSelectedCountryId(snap.countryId);
      setSelectedCityId(snap.cityId);
      setDescription(snap.description);
    }
    setDraftTimelineItems(null);
    setInfoSaveError(null);
    setIsEditingInfo(false);
  }

  function timelineItemCreatePayload(item: TimelineItem) {
    return {
      dayNumber: item.dayNumber,
      visitDate: item.visitDate,
      cityId: item.cityId,
      category: item.category,
      foodSubcategory: item.foodSubcategory,
      name: item.name,
      googlePlaceId: item.googlePlaceId,
      visitOrder: item.visitOrder,
      memo: item.memo,
    };
  }

  function timelineItemUpdatePayload(item: TimelineItem) {
    return {
      dayNumber: item.dayNumber,
      visitDate: item.visitDate,
      category: item.category,
      foodSubcategory: item.foodSubcategory,
      name: item.name,
      memo: item.memo,
      visitOrder: item.visitOrder,
      cityId: item.cityId,
      googlePlaceId: item.googlePlaceId,
    };
  }

  /**
   * 여행 PATCH 자체가 "현재 DB에 있는 모든 일정 항목의 dayNumber가 이미 새 시작일과 맞아야 한다"를
   * 검사한다(TravelUpdateService.validateTimelineDates) — 개별 일정 항목 PATCH는 반대로 "제출하는
   * dayNumber가 현재(아직 안 바뀐) 시작일과 맞아야 한다"를 검사한다(TimelineItem.validateDayAndDate).
   * 시작일 자체가 바뀌는 경우 이 둘을 동시에 만족시킬 수 없어서(순환), 살아남는 기존 배정 항목들을
   * 일단 전부 미배정으로 비워 여행 PATCH를 통과시키고, PATCH 이후에 최종 배정 상태로 다시 채운다.
   */
  async function commitTimelineItemChanges(
    original: TimelineItem[],
    draft: TimelineItem[],
    oldRange: { start: Date; end: Date },
    startChanged: boolean,
  ) {
    if (!accessToken || !id) return () => Promise.resolve();
    const oldStart = new Date(oldRange.start.getFullYear(), oldRange.start.getMonth(), oldRange.start.getDate());
    const oldEnd = new Date(oldRange.end.getFullYear(), oldRange.end.getMonth(), oldRange.end.getDate());
    function needsNewRangeFirst(item: TimelineItem): boolean {
      if (!item.visitDate) return false;
      if (startChanged) return true;
      const visitDate = parseIsoDate(item.visitDate);
      return visitDate.getTime() < oldStart.getTime() || visitDate.getTime() > oldEnd.getTime();
    }

    const draftIds = new Set(draft.map((item) => item.timelineItemId));

    // 1) 삭제
    for (const item of original) {
      if (!draftIds.has(item.timelineItemId)) {
        await deleteTimelineItem(accessToken, id, item.timelineItemId);
      }
    }

    // 2) 시작일이 바뀌면, 살아남는 기존 배정 항목을 일단 전부 미배정으로 비워서 여행 PATCH의
    //    "모든 기존 항목이 새 시작일과 이미 맞아야 한다" 검사를 통과시킨다. 최종 배정은 3)에서 다시 채운다.
    if (startChanged) {
      for (const item of original) {
        if (!draftIds.has(item.timelineItemId)) continue;
        if (item.dayNumber != null) {
          await updateTimelineItem(accessToken, id, item.timelineItemId, { dayNumber: null, visitDate: null });
        }
      }
    }

    // 3) 생성/수정 — 옛 기간 안에서 처리 가능한 건 먼저, 새 기간이 있어야 하는 건 나중으로 미룬다.
    const originalById = new Map(original.map((item) => [item.timelineItemId, item]));
    const deferred: (() => Promise<unknown>)[] = [];
    for (const item of draft) {
      if (item.timelineItemId.startsWith(NEW_ITEM_PREFIX)) {
        const run = () => createTimelineItem(accessToken, id, timelineItemCreatePayload(item));
        if (needsNewRangeFirst(item)) deferred.push(run);
        else await run();
        continue;
      }
      const original_ = originalById.get(item.timelineItemId);
      if (!original_) continue;
      const changed =
        original_.dayNumber !== item.dayNumber ||
        original_.visitDate !== item.visitDate ||
        original_.category !== item.category ||
        original_.foodSubcategory !== item.foodSubcategory ||
        original_.name !== item.name ||
        original_.memo !== item.memo ||
        original_.visitOrder !== item.visitOrder ||
        original_.cityId !== item.cityId ||
        original_.googlePlaceId !== item.googlePlaceId;
      if (changed) {
        const run = () => updateTimelineItem(accessToken, id, item.timelineItemId, timelineItemUpdatePayload(item));
        if (needsNewRangeFirst(item)) deferred.push(run);
        else await run();
      }
    }

    return async () => {
      for (const run of deferred) await run();
    };
  }

  async function saveEditInfo() {
    if (!accessToken || !detail) return;
    setInfoSaveError(null);
    const patch: Parameters<typeof updateTravel>[2] = {
      title: titleDraft.trim() || detail.title,
      startDate: formatIsoDate(dateRange.start),
      endDate: formatIsoDate(dateRange.end),
      comment: description,
      version: detail.version,
    };
    if (selectedCountryId != null) patch.countryId = selectedCountryId;
    if (selectedCityId != null) patch.cityId = selectedCityId;
    const companionType = COMPANION_TYPE_BY_LABEL[companion];
    if (companionType) patch.companionType = companionType;

    const startChanged = patch.startDate !== detail.startDate;
    const datesChanged = startChanged || patch.endDate !== detail.endDate;

    try {
      let applyDeferred = async () => {};
      if (draftTimelineItems) {
        const reconciled = datesChanged
          ? reconcileForDateRange(draftTimelineItems, dateRange.start, dateRange.end)
          : draftTimelineItems;
        const itemsToCommit = normalizeVisitOrders(reconciled);
        applyDeferred = await commitTimelineItemChanges(
          detail.timelineItems,
          itemsToCommit,
          { start: parseIsoDate(detail.startDate), end: parseIsoDate(detail.endDate) },
          startChanged,
        );
      }
      await updateTravel(accessToken, detail.travelId, patch);
      await applyDeferred();
      setDraftTimelineItems(null);
      setIsEditingInfo(false);
      refreshDetail();
    } catch (e) {
      console.error("여행 정보 저장 실패", e);
      setInfoSaveError(e instanceof ApiError ? e.message : "저장에 실패했어요. 다시 시도해주세요.");
    }
  }

  const isOwner = detail?.permission === "OWNER";
  const canEditInfo = isOwner || detail?.permission === "READ_WRITE";

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
        onInvite={handleInvite}
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
