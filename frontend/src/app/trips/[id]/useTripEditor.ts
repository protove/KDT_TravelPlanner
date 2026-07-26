import * as React from "react";
import type { useRouter } from "next/navigation";
import {
  fetchTravelDetail,
  updateTravel,
  deleteTravel,
  type TravelDetail,
  type TimelineItem,
} from "@/lib/api/travel";
import { fetchCountries, fetchCitiesByCountry, type Country, type City } from "@/lib/api/location";
import { fetchTravelMembers, updateMemberRole, removeMember, leaveTravel, type TravelMember } from "@/lib/api/members";
import { createInvitation } from "@/lib/api/invitations";
import { toTravelRole } from "@/lib/api/permission";
import { createTimelineItem, updateTimelineItem, deleteTimelineItem } from "@/lib/api/timelineItems";
import { ApiError } from "@/lib/api/client";
import type { Permission } from "@/components/molecules/PermissionSelect";
import {
  COMPANION_OPTIONS,
  UUID_PATTERN,
  COMPANION_LABELS,
  COMPANION_TYPE_BY_LABEL,
  NEW_ITEM_PREFIX,
  parseIsoDate,
  formatIsoDate,
  reconcileForDateRange,
  normalizeVisitOrders,
} from "./utils";

/**
 * 여행 상세 페이지의 데이터(여행 정보/국가·도시/멤버)와 "정보 수정" 편집 흐름을 전부 묶은 훅.
 * page.tsx가 900줄 넘게 커졌던 원인 중 하나라 분리했다 — 이름은 page.tsx에서 쓰던 것과
 * 그대로 맞춰뒀으니 사용하는 쪽에서는 구조분해만 하면 기존 JSX를 그대로 쓸 수 있다.
 */
export function useTripEditor(id: string | undefined, accessToken: string | null, router: ReturnType<typeof useRouter>) {
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

  /**
   * "정보 수정" 중에 달력에서 여행 기간을 바꾸면, 예전엔 이 화면에 아무 반응이 없다가
   * "저장"을 눌러야만(saveEditInfo) 배정된 일정이 조용히 재정리됐다 — 그래서 사용자
   * 입장에선 날짜를 바꿔도 일정이 예전 날짜에 그대로 붙어있는 것처럼 보여 "저장해도
   * 안 바뀐다"는 오해를 샀다. 이제 기간이 바뀌는 즉시 draftTimelineItems를 새 기간
   * 기준으로 재정리해서, 화면(일차 탭/미배정 목록)에 바로 반영되게 한다.
   * 실제 저장 시점의 재정리(saveEditInfo 안 reconcileForDateRange)는 그대로 두는데,
   * 이미 정리된 값을 다시 정리하는 거라 안전하다(그대로 유지).
   */
  React.useEffect(() => {
    setDraftTimelineItems((prev) =>
      prev ? normalizeVisitOrders(reconcileForDateRange(prev, dateRange.start, dateRange.end)) : prev,
    );
  }, [dateRange]);

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

  /** onSuccess는 초대 다이얼로그를 닫는 등 UI 쪽 뒷정리를 위한 콜백 — 다이얼로그 표시 상태는 page.tsx가 갖고 있다. */
  async function handleInvite(onSuccess: () => void) {
    if (!accessToken || !id) return;
    setInviteError(null);
    try {
      await createInvitation(accessToken, id, {
        nickname: inviteNickname.trim(),
        role: toTravelRole(invitePermission),
      });
      setInviteNickname("");
      onSuccess();
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

  return {
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
    refreshDetail,
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
  };
}
