import * as React from "react";
import type { Country } from "@/lib/api/location";
import { type TimelineItem } from "@/lib/api/travel";
import { searchNearbyPlaces, searchPlaces, type PlaceSearchResult } from "@/lib/api/places";
import { type PlaceDateChip, type TimelineCategoryOption } from "@/components/organisms/PlaceModal";
import { NEW_ITEM_PREFIX, formatIsoDate, computeNextVisitOrder, type getDateTabs } from "./utils";
import { hasIncompleteHangul, hasRepeatedCharSpam } from "@/lib/validation/text";

type DateTab = ReturnType<typeof getDateTabs>[number];

// 나라 미선택 시 장소 검색(Google Places)에 대신 쓸 기본 국가 코드.
// 결과가 이 나라로 편향(bias)되니 완벽하진 않지만, 나라를 안 골랐다고 검색 자체가 막히는 것보단 낫다.
const DEFAULT_COUNTRY_CODE = "KR";
const NEARBY_SEARCH_RADIUS_METERS = 1500;

interface UsePlaceEditorParams {
  accessToken: string | null;
  countries: Country[];
  selectedCountryId: number | null;
  selectedCityId: number | null;
  dateTabs: DateTab[];
  timelineItems: TimelineItem[];
  setDraftTimelineItems: React.Dispatch<React.SetStateAction<TimelineItem[] | null>>;
}

/**
 * "목적지 추가/수정" 모달과 장소 검색 관련 상태·로직을 전부 묶은 훅.
 * page.tsx에서 쓰던 이름 그대로 반환하니, 구조분해만 하면 기존 JSX를 그대로 쓸 수 있다.
 */
export function usePlaceEditor({
  accessToken,
  countries,
  selectedCountryId,
  selectedCityId,
  dateTabs,
  timelineItems,
  setDraftTimelineItems,
}: UsePlaceEditorParams) {
  const [editingPlace, setEditingPlace] = React.useState<TimelineItem | null>(null);
  const [addingPlace, setAddingPlace] = React.useState(false);
  const [placeDraftName, setPlaceDraftName] = React.useState("");
  const [placeNameError, setPlaceNameError] = React.useState<string | null>(null);
  const [placeDraftNote, setPlaceDraftNote] = React.useState("");
  const [placeDraftCategory, setPlaceDraftCategory] = React.useState<TimelineCategoryOption>("관광지");
  const [placeDraftFoodSubcategory, setPlaceDraftFoodSubcategory] = React.useState("");
  const [placeDraftDayNumbers, setPlaceDraftDayNumbers] = React.useState<number[]>([]);
  const [placeQuery, setPlaceQueryState] = React.useState("");
  const [placeResults, setPlaceResults] = React.useState<PlaceSearchResult[]>([]);
  const [placeSearchLoading, setPlaceSearchLoading] = React.useState(false);
  const [placeSearchError, setPlaceSearchError] = React.useState<string | null>(null);
  const [selectedGooglePlaceId, setSelectedGooglePlaceId] = React.useState<string | null>(null);
  // 검색 결과에서 고른 장소의 좌표 — 저장 전에도 지도에 바로 미리보기 마커를 찍기 위한 값.
  const [selectedPlaceCoords, setSelectedPlaceCoords] = React.useState<{ lat: number; lng: number } | null>(null);
  // 아직 서버에 저장 안 된(=draft) 신규 일정 항목들의 좌표. timelineItemId -> {lat, lng}.
  // 저장하면 서버가 실제 좌표를 다시 내려주니, 그때부터는 이 값 대신 mapPoints 쪽을 쓰면 된다.
  const [draftPlaceCoords, setDraftPlaceCoords] = React.useState<Record<string, { lat: number; lng: number }>>({});

  React.useEffect(() => {
    const countryCode = countries.find((c) => c.countryId === selectedCountryId)?.code ?? DEFAULT_COUNTRY_CODE;
    const trimmedQuery = placeQuery.trim();
    if (!accessToken || !trimmedQuery) return;
    let active = true;
    const handle = setTimeout(() => {
      setPlaceSearchLoading(true);
      setPlaceSearchError(null);
      searchPlaces(accessToken, trimmedQuery, countryCode)
        .then((results) => {
          if (active) setPlaceResults(results);
        })
        .catch(() => {
          if (!active) return;
          setPlaceResults([]);
          setPlaceSearchError("장소를 불러오지 못했어요. 다시 검색해 주세요.");
        })
        .finally(() => {
          if (active) setPlaceSearchLoading(false);
        });
    }, 300);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [accessToken, placeQuery, countries, selectedCountryId]);

  function setPlaceQuery(query: string) {
    setPlaceQueryState(query);
    if (!query.trim()) {
      setPlaceResults([]);
      setPlaceSearchLoading(false);
      setPlaceSearchError(null);
    }
  }

  function clearPlaceSearch() {
    setPlaceQueryState("");
    setPlaceResults([]);
    setPlaceSearchLoading(false);
    setPlaceSearchError(null);
  }

  async function searchNearbyFromMapCenter(center: { lat: number; lng: number }) {
    if (!accessToken) {
      setPlaceSearchError("로그인 후 주변 장소를 찾을 수 있어요.");
      return;
    }

    setAddingPlace(false);
    setEditingPlace(null);
    setPlaceDraftName("");
    setPlaceDraftNote("");
    setPlaceDraftCategory("관광지");
    setPlaceDraftFoodSubcategory("");
    setPlaceDraftDayNumbers([]);
    setPlaceQueryState("");
    setSelectedGooglePlaceId(null);
    setSelectedPlaceCoords(null);
    setPlaceSearchLoading(true);
    setPlaceSearchError(null);

    try {
      const results = await searchNearbyPlaces(accessToken, {
        latitude: center.lat,
        longitude: center.lng,
        radiusMeters: NEARBY_SEARCH_RADIUS_METERS,
      });
      setPlaceResults(results);
      if (results.length === 0) {
        setPlaceSearchError("현재 지도 주변에서 찾은 장소가 없어요.");
        setAddingPlace(true);
      }
    } catch {
      setPlaceResults([]);
      setPlaceSearchError("주변 장소를 불러오지 못했어요. 지도를 조금 이동한 뒤 다시 시도해 주세요.");
      setAddingPlace(true);
    } finally {
      setPlaceSearchLoading(false);
    }
  }

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
    setPlaceNameError(null);
    setPlaceDraftNote("");
    setPlaceDraftCategory("관광지");
    setPlaceDraftFoodSubcategory("");
    setPlaceDraftDayNumbers([]);
    setPlaceQueryState("");
    setPlaceResults([]);
    setPlaceSearchError(null);
    setPlaceSearchLoading(false);
    setSelectedGooglePlaceId(null);
    setSelectedPlaceCoords(null);
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
      if (hasIncompleteHangul(name)) {
        setPlaceNameError("완성되지 않은 한글(자음/모음)은 사용할 수 없어요.");
        return;
      }
      if (hasRepeatedCharSpam(name)) {
        setPlaceNameError("같은 문자를 5번 이상 반복할 수 없어요.");
        return;
      }
      setPlaceNameError(null);
      const newItemId = `${NEW_ITEM_PREFIX}${crypto.randomUUID()}`;
      setDraftTimelineItems((prev) => {
        const base = prev ?? [];
        const newItem: TimelineItem = {
          timelineItemId: newItemId,
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
      // 장소 검색으로 골라서 좌표를 아는 경우, 저장 전이라도 지도에 바로 미리보기 마커를 찍는다.
      if (selectedPlaceCoords) {
        setDraftPlaceCoords((prev) => ({ ...prev, [newItemId]: selectedPlaceCoords }));
      }
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
    setDraftPlaceCoords((prev) => {
      if (!(itemId in prev)) return prev;
      const rest = { ...prev };
      delete rest[itemId];
      return rest;
    });
  }

  const dateChips: PlaceDateChip[] = dateTabs.map((tab) => ({
    label: `${tab.date.getMonth() + 1}.${tab.date.getDate()}`,
    selected: placeDraftDayNumbers.includes(Number(tab.key) + 1),
  }));

  return {
    editingPlace,
    setEditingPlace,
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
    placeSearchLoading,
    placeSearchError,
    clearPlaceSearch,
    searchNearbyFromMapCenter,
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
  };
}
