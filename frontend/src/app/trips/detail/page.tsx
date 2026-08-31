"use client";

import * as React from "react";
import {
  useRouter,
  useSearchParams,
} from "next/navigation";

import { Button } from "@/components/atoms/Button";
import { Textarea } from "@/components/atoms/Textarea";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { InviteDialog } from "@/components/organisms/InviteDialog";
import { MapPanel } from "@/components/organisms/MapPanel";
import {
  ParticipantManageDialog,
  type Participant,
} from "@/components/organisms/ParticipantManageDialog";
import {
  PlaceModal,
  type PlaceSearchResultOption,
} from "@/components/organisms/PlaceModal";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import { TripDetailHeader } from "@/components/organisms/TripDetailHeader";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { TripDetailPageSkeleton } from "@/components/templates/TripDetailPageSkeleton";

import {
  toPermission,
  type TravelRole,
} from "@/lib/api/permission";

import {
  searchPlaces,
  type PlaceSearchResult,
} from "@/lib/api/places";

import {
  previewTravelRoute,
  type TravelRoutePreviewResponse,
} from "@/lib/api/routes";

import { useAuthStore } from "@/lib/stores/useAuthStore";
import { DESCRIPTION_MAX_LENGTH } from "@/lib/validation/text";

import {
  COMPANION_OPTIONS,
  UUID_PATTERN,
  getDateTabs,
} from "./utils";

import { useMapPoints } from "./useMapPoints";
import { usePlaceEditor } from "./usePlaceEditor";
import { useTripEditor } from "./useTripEditor";

type ExtendedPlaceSearchResult =
  PlaceSearchResult & {
    userRatingCount?:
      | number
      | null;

    formattedAddress?:
      | string
      | null;
  };

export default function TripDetailPage() {
  return (
    <React.Suspense fallback={null}>
      <TripDetailContent />
    </React.Suspense>
  );
}

function TripDetailContent() {
  const router =
    useRouter();

  const searchParams =
    useSearchParams();

  const id =
    searchParams.get("id") ??
    undefined;

  const isLoggedIn =
    useAuthStore(
      (state) =>
        state.isLoggedIn
    );

  const isInitializing =
    useAuthStore(
      (state) =>
        state.isInitializing
    );

  const user =
    useAuthStore(
      (state) =>
        state.user
    );

  const accessToken =
    useAuthStore(
      (state) =>
        state.accessToken
    );

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
  } =
    useTripEditor(
      id,
      accessToken,
      router
    );

  const [
    activeDay,
    setActiveDay,
  ] =
    React.useState("0");

  const [
    showCalendar,
    setShowCalendar,
  ] =
    React.useState(false);

  const [
    showDeleteConfirm,
    setShowDeleteConfirm,
  ] =
    React.useState(false);

  const [
    showLeaveConfirm,
    setShowLeaveConfirm,
  ] =
    React.useState(false);

  const [
    showInvite,
    setShowInvite,
  ] =
    React.useState(false);

  const [
    showManage,
    setShowManage,
  ] =
    React.useState(false);

  const [
    mapSearchQuery,
    setMapSearchQuery,
  ] =
    React.useState("");

  const [
    mapSearchResults,
    setMapSearchResults,
  ] =
    React.useState<
      ExtendedPlaceSearchResult[]
    >([]);

  const [
    mapSearchLoading,
    setMapSearchLoading,
  ] =
    React.useState(false);

  const [
    mapSearchError,
    setMapSearchError,
  ] =
    React.useState<
      string | null
    >(null);

  const [
    selectedMapPlace,
    setSelectedMapPlace,
  ] =
    React.useState<
      ExtendedPlaceSearchResult
      | null
    >(null);

  const mapSearchRequestIdRef =
    React.useRef(0);

  const [
    showUnassignedMarkers,
    setShowUnassignedMarkers,
  ] =
    React.useState(true);

  const [
    route,
    setRoute,
  ] =
    React.useState<
      TravelRoutePreviewResponse
      | null
    >(null);

  const [
    routeLoading,
    setRouteLoading,
  ] =
    React.useState(false);

  const [
    routeError,
    setRouteError,
  ] =
    React.useState<
      string | null
    >(null);

  const [
    routeAutoRefreshEnabled,
    setRouteAutoRefreshEnabled,
  ] =
    React.useState(false);

  const routeRequestIdRef =
    React.useRef(0);

  const lastRoutePreviewSignatureRef =
    React.useRef<
      string | null
    >(null);

  const dateTabs =
    getDateTabs(
      dateRange.start,
      dateRange.end
    );

  const timelineItems =
    draftTimelineItems ??
    detail?.timelineItems ??
    [];

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
  } =
    usePlaceEditor({
      accessToken,

      countries,

      selectedCountryId,
      selectedCityId,

      dateTabs,

      timelineItems,

      setDraftTimelineItems,
    });

  const visibleActiveDay =
    Number(activeDay) <
    dateTabs.length
      ? activeDay
      : "0";

  const activeDayNumber =
    Number(
      visibleActiveDay
    ) + 1;

  const mapPoints =
    useMapPoints(
      accessToken,
      id,
      activeDayNumber,
      detail?.timelineItems
    );

  React.useEffect(() => {
    if (
      !isInitializing &&
      !isLoggedIn
    ) {
      router.replace("/");
    }
  }, [
    isInitializing,
    isLoggedIn,
    router,
  ]);

  React.useEffect(() => {
    if (
      !id ||
      !UUID_PATTERN.test(id)
    ) {
      router.replace(
        "/403"
      );
    }
  }, [
    id,
    router,
  ]);

  function getTimelineItemPlaceId(
    item:
      (typeof timelineItems)[number]
  ):
    | string
    | undefined {
    const googlePlaceId =
      item.googlePlaceId;

    if (
      typeof googlePlaceId !==
        "string" ||
      googlePlaceId.trim().length ===
        0
    ) {
      return undefined;
    }

    return googlePlaceId.trim();
  }

  const savedCoordsById =
    new Map(
      mapPoints.map(
        (point) => [
          point.timelineItemId,

          {
            lat:
              point.latitude,

            lng:
              point.longitude,
          },
        ]
      )
    );

  const knownCoordsByName =
    new Map<
      string,
      {
        lat: number;
        lng: number;
      }
    >();

  mapPoints.forEach(
    (point) => {
      knownCoordsByName.set(
        point.name.trim(),

        {
          lat:
            point.latitude,

          lng:
            point.longitude,
        }
      );
    }
  );

  timelineItems.forEach(
    (item) => {
      const coords =
        draftPlaceCoords[
          item.timelineItemId
        ];

      if (!coords) {
        return;
      }

      knownCoordsByName.set(
        item.name.trim(),

        {
          lat:
            coords.lat,

          lng:
            coords.lng,
        }
      );
    }
  );

  function getTimelineItemCoords(
    item:
      (typeof timelineItems)[number]
  ):
    | {
        lat: number;
        lng: number;
      }
    | undefined {
    const draftCoords =
      draftPlaceCoords[
        item.timelineItemId
      ];

    if (draftCoords) {
      return {
        lat:
          draftCoords.lat,

        lng:
          draftCoords.lng,
      };
    }

    const savedCoords =
      savedCoordsById.get(
        item.timelineItemId
      );

    if (savedCoords) {
      return savedCoords;
    }

    return knownCoordsByName.get(
      item.name.trim()
    );
  }

  const activeDayItems =
    timelineItems
      .filter(
        (item) =>
          item.dayNumber ===
          activeDayNumber
      )
      .sort(
        (
          left,
          right
        ) =>
          left.visitOrder -
          right.visitOrder
      )
      .map(
        (item) => ({
          id:
            item.timelineItemId,

          placeName:
            item.name,

          note:
            item.memo ||
            undefined,
        })
      );

  const unassignedPlaces =
    timelineItems
      .filter(
        (item) =>
          item.dayNumber ===
          null
      )
      .sort(
        (
          left,
          right
        ) =>
          left.visitOrder -
          right.visitOrder
      )
      .map(
        (item) => ({
          id:
            item.timelineItemId,

          name:
            item.name,

          note:
            item.memo ||
            undefined,
        })
      );

  const selectedCountryName =
    countries.find(
      (country) =>
        country.countryId ===
        selectedCountryId
    )?.nameKo ??
    "나라 미지정";

  const selectedCityName =
    cities.find(
      (city) =>
        city.cityId ===
        selectedCityId
    )?.nameKo ??
    "도시 미지정";

  const selectedCountryCode =
    countries.find(
      (country) =>
        country.countryId ===
        selectedCountryId
    )?.code ??
    "KR";

  const assignedMarkers =
    timelineItems
      .filter(
        (item) =>
          item.dayNumber ===
          activeDayNumber
      )
      .flatMap(
        (item) => {
          const coords =
            getTimelineItemCoords(
              item
            );

          if (!coords) {
            return [];
          }

          return [
            {
              id:
                item.timelineItemId,

              name:
                item.name,

              lat:
                coords.lat,

              lng:
                coords.lng,

              placeId:
                getTimelineItemPlaceId(
                  item
                ),

              kind:
                "assigned" as const,
            },
          ];
        }
      );

  const unassignedMarkers =
    timelineItems
      .filter(
        (item) =>
          item.dayNumber ===
          null
      )
      .flatMap(
        (item) => {
          const coords =
            getTimelineItemCoords(
              item
            );

          if (!coords) {
            return [];
          }

          return [
            {
              id:
                item.timelineItemId,

              name:
                item.name,

              lat:
                coords.lat,

              lng:
                coords.lng,

              placeId:
                getTimelineItemPlaceId(
                  item
                ),

              kind:
                "unassigned" as const,
            },
          ];
        }
      );

  const nearbyMarkers =
    !addingPlace
      ? (
          placeResults as
            ExtendedPlaceSearchResult[]
        ).map(
          (place) => ({
            id:
              `nearby:${place.placeId}`,

            placeId:
              place.placeId,

            name:
              place.name,

            lat:
              place.latitude,

            lng:
              place.longitude,

            rating:
              place.rating,

            userRatingCount:
              place.userRatingCount ??
              null,

            formattedAddress:
              place.formattedAddress ??
              null,

            kind:
              "nearby" as const,
          })
        )
      : [];

  const searchMarker =
    selectedMapPlace
      ? [
          {
            id:
              `search:${selectedMapPlace.placeId}`,

            placeId:
              selectedMapPlace.placeId,

            name:
              selectedMapPlace.name,

            lat:
              selectedMapPlace.latitude,

            lng:
              selectedMapPlace.longitude,

            rating:
              selectedMapPlace.rating,

            userRatingCount:
              selectedMapPlace.userRatingCount ??
              null,

            formattedAddress:
              selectedMapPlace.formattedAddress ??
              null,

            kind:
              "search" as const,
          },
        ]
      : [];

  const mapMarkers = [
    ...assignedMarkers,

    ...(showUnassignedMarkers
      ? unassignedMarkers
      : []),

    ...nearbyMarkers,

    ...searchMarker,
  ];

  type RoutePreviewItem = {
    timelineItemId: string;
    googlePlaceId: string | null;
    latitude: number | null;
    longitude: number | null;
    visitOrder: number;
  };

  const routePreviewItems:
    RoutePreviewItem[] =
    timelineItems
      .filter(
        (item) =>
          item.dayNumber ===
          activeDayNumber
      )
      .sort(
        (
          left,
          right
        ) =>
          left.visitOrder -
          right.visitOrder
      )
      .map(
        (item) => {
          const coords =
            getTimelineItemCoords(
              item
            );

          return {
            timelineItemId:
              item.timelineItemId,

            googlePlaceId:
              getTimelineItemPlaceId(
                item
              ) ??
              null,

            latitude:
              coords?.lat ??
              null,

            longitude:
              coords?.lng ??
              null,

            visitOrder:
              item.visitOrder,
          };
        }
      );

  const routePreviewSignature =
    JSON.stringify(
      routePreviewItems
    );

  async function handleOptimizeRoute() {
    if (
      !accessToken ||
      !id
    ) {
      setRoute(null);

      setRouteError(
        "로그인 정보 또는 여행 정보를 확인할 수 없어요."
      );

      return;
    }

    if (routeLoading) {
      return;
    }

    if (
      routePreviewItems.length <
      2
    ) {
      setRoute(null);

      setRouteError(
        "경로를 표시하려면 현재 날짜에 장소를 2개 이상 배정해 주세요."
      );

      return;
    }

    if (
      routePreviewItems.length >
      27
    ) {
      setRoute(null);

      setRouteError(
        "한 번에 경로를 계산할 수 있는 장소 수를 초과했어요."
      );

      return;
    }

    const invalidRouteWaypoint =
      routePreviewItems.some(
        (item) =>
          !item.googlePlaceId ||
          item.latitude === null ||
          item.longitude === null ||
          !Number.isFinite(
            item.latitude
          ) ||
          !Number.isFinite(
            item.longitude
          )
      );

    if (
      invalidRouteWaypoint
    ) {
      setRoute(null);

      setRouteError(
        "경로를 계산할 수 없는 장소가 포함되어 있어요. Google 지도에서 장소를 다시 선택해 주세요."
      );

      return;
    }

    clearPlaceSearch();

    const requestId =
      ++routeRequestIdRef.current;

    setRouteLoading(
      true
    );

    setRouteError(
      null
    );

    try {
      const result =
        await previewTravelRoute(
          accessToken,
          id,
          {
            dayNumber:
              activeDayNumber,

            transportationType:
              "TRANSIT",

            waypoints:
              routePreviewItems.map(
                (item) => ({
                  googlePlaceId:
                    item.googlePlaceId!,

                  latitude:
                    item.latitude!,

                  longitude:
                    item.longitude!,
                })
              ),
          }
        );

      if (
        requestId !==
        routeRequestIdRef.current
      ) {
        return;
      }

      if (
        result.encodedPolylines.length ===
        0
      ) {
        setRoute(
          null
        );

        setRouteError(
          "현재 일정으로 대중교통 경로를 표시할 수 없어요."
        );

        return;
      }

      setRoute(
        result
      );

      setRouteError(
        null
      );

      lastRoutePreviewSignatureRef.current =
        routePreviewSignature;

      setRouteAutoRefreshEnabled(
        true
      );
    } catch {
      if (
        requestId !==
        routeRequestIdRef.current
      ) {
        return;
      }

      setRoute(
        null
      );

      setRouteError(
        "경로를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."
      );
    } finally {
      if (
        requestId ===
        routeRequestIdRef.current
      ) {
        setRouteLoading(
          false
        );
      }
    }
  }

  React.useEffect(() => {
    if (
      !routeAutoRefreshEnabled ||
      !accessToken ||
      !id
    ) {
      return;
    }

    if (
      lastRoutePreviewSignatureRef.current ===
      routePreviewSignature
    ) {
      return;
    }

    const timer =
      window.setTimeout(
        () => {
          const currentPreviewItems =
            JSON.parse(
              routePreviewSignature
            ) as
              RoutePreviewItem[];

          if (
            currentPreviewItems.length <
            2
          ) {
            ++routeRequestIdRef.current;

            lastRoutePreviewSignatureRef.current =
              routePreviewSignature;

            setRoute(
              null
            );

            setRouteLoading(
              false
            );

            setRouteError(
              "경로를 표시하려면 현재 날짜에 장소를 2개 이상 배정해 주세요."
            );

            return;
          }

          if (
            currentPreviewItems.length >
            27
          ) {
            ++routeRequestIdRef.current;

            lastRoutePreviewSignatureRef.current =
              routePreviewSignature;

            setRoute(
              null
            );

            setRouteLoading(
              false
            );

            setRouteError(
              "한 번에 경로를 계산할 수 있는 장소 수를 초과했어요."
            );

            return;
          }

          const invalidRouteWaypoint =
            currentPreviewItems.some(
              (item) =>
                !item.googlePlaceId ||
                item.latitude === null ||
                item.longitude === null ||
                !Number.isFinite(
                  item.latitude
                ) ||
                !Number.isFinite(
                  item.longitude
                )
            );

          if (
            invalidRouteWaypoint
          ) {
            ++routeRequestIdRef.current;

            lastRoutePreviewSignatureRef.current =
              routePreviewSignature;

            setRoute(
              null
            );

            setRouteLoading(
              false
            );

            setRouteError(
              "경로를 계산할 수 없는 장소가 포함되어 있어요. Google 지도에서 장소를 다시 선택해 주세요."
            );

            return;
          }

          const requestId =
            ++routeRequestIdRef.current;

          setRouteLoading(
            true
          );

          setRouteError(
            null
          );

          void previewTravelRoute(
            accessToken,
            id,
            {
              dayNumber:
                activeDayNumber,

              transportationType:
                "TRANSIT",

              waypoints:
                currentPreviewItems.map(
                  (item) => ({
                    googlePlaceId:
                      item.googlePlaceId!,

                    latitude:
                      item.latitude!,

                    longitude:
                      item.longitude!,
                  })
                ),
            }
          )
            .then(
              (result) => {
                if (
                  requestId !==
                  routeRequestIdRef.current
                ) {
                  return;
                }

                lastRoutePreviewSignatureRef.current =
                  routePreviewSignature;

                if (
                  result.encodedPolylines.length ===
                  0
                ) {
                  setRoute(
                    null
                  );

                  setRouteError(
                    "현재 일정으로 대중교통 경로를 표시할 수 없어요."
                  );

                  return;
                }

                setRoute(
                  result
                );

                setRouteError(
                  null
                );
              }
            )
            .catch(() => {
              if (
                requestId !==
                routeRequestIdRef.current
              ) {
                return;
              }

              setRoute(
                null
              );

              setRouteError(
                "경로를 다시 계산하지 못했어요."
              );
            })
            .finally(() => {
              if (
                requestId ===
                routeRequestIdRef.current
              ) {
                setRouteLoading(
                  false
                );
              }
            });
        },
        250
      );

    return () => {
      window.clearTimeout(
        timer
      );
    };
  }, [
    routeAutoRefreshEnabled,
    accessToken,
    id,
    activeDayNumber,
    routePreviewSignature,
  ]);

  if (
    isInitializing ||
    !isLoggedIn ||
    !user
  ) {
    return null;
  }

  if (!detail) {
    return (
      <TripDetailPageSkeleton />
    );
  }

  const canEditSchedule =
    canEditInfo &&
    isEditingInfo;

  function handleClearMapSearch() {
    ++mapSearchRequestIdRef.current;

    setMapSearchQuery(
      ""
    );

    setMapSearchResults(
      []
    );

    setMapSearchLoading(
      false
    );

    setMapSearchError(
      null
    );

    setSelectedMapPlace(
      null
    );
  }

  function handleDayChange(
    day: string
  ) {
    setActiveDay(
      day
    );

    handleClearMapSearch();

    clearPlaceSearch();

    ++routeRequestIdRef.current;

    setRoute(
      null
    );

    setRouteLoading(
      false
    );

    setRouteError(
      null
    );

    setRouteAutoRefreshEnabled(
      false
    );

    lastRoutePreviewSignatureRef.current =
      null;
  }

  function handleSearchNearby(
    center: {
      lat: number;
      lng: number;
    }
  ) {
    void searchNearbyFromMapCenter(
      center
    );
  }

  function handleMapMarkerClick(
    markerId: string
  ) {
    if (
      markerId.startsWith(
        "nearby:"
      )
    ) {
      const placeId =
        markerId.slice(
          "nearby:".length
        );

      const place =
        (
          placeResults as
            ExtendedPlaceSearchResult[]
        ).find(
          (result) =>
            result.placeId ===
            placeId
        );

      if (!place) {
        return;
      }

      setSelectedMapPlace(
        place
      );

      setAddingPlace(
        false
      );

      return;
    }

    if (
      markerId.startsWith(
        "search:"
      )
    ) {
      return;
    }
  }

  async function handleMapSearchSubmit() {
    const query =
      mapSearchQuery.trim();

    if (!query) {
      handleClearMapSearch();

      return;
    }

    if (!accessToken) {
      setMapSearchResults(
        []
      );

      setMapSearchError(
        "로그인 후 장소를 검색할 수 있어요."
      );

      return;
    }

    const requestId =
      ++mapSearchRequestIdRef.current;

    setMapSearchLoading(
      true
    );

    setMapSearchError(
      null
    );

    try {
      const results =
        (
          await searchPlaces(
            accessToken,
            query,
            selectedCountryCode
          )
        ) as
          ExtendedPlaceSearchResult[];

      if (
        requestId !==
        mapSearchRequestIdRef.current
      ) {
        return;
      }

      setMapSearchResults(
        results
      );

      if (
        results.length ===
        0
      ) {
        setMapSearchError(
          "검색 결과가 없어요."
        );
      }
    } catch {
      if (
        requestId !==
        mapSearchRequestIdRef.current
      ) {
        return;
      }

      setMapSearchResults(
        []
      );

      setMapSearchError(
        "장소를 검색하지 못했어요."
      );
    } finally {
      if (
        requestId ===
        mapSearchRequestIdRef.current
      ) {
        setMapSearchLoading(
          false
        );
      }
    }
  }

  function handleSelectMapSearchResult(
    place:
      ExtendedPlaceSearchResult
  ) {
    setSelectedMapPlace(
      place
    );

    setMapSearchResults(
      []
    );

    setMapSearchError(
      null
    );
  }

  function handleAddSelectedMapPlace() {
    if (
      !selectedMapPlace
    ) {
      return;
    }

    setEditingPlace(
      null
    );

    setAddingPlace(
      true
    );

    setPlaceDraftName(
      selectedMapPlace.name
    );

    setSelectedGooglePlaceId(
      selectedMapPlace.placeId
    );

    setSelectedPlaceCoords({
      lat:
        selectedMapPlace.latitude,

      lng:
        selectedMapPlace.longitude,
    });

    clearPlaceSearch();

    setMapSearchResults(
      []
    );

    setMapSearchError(
      null
    );

    setSelectedMapPlace(
      null
    );
  }

  function handleReorderDay(
    orderedIds:
      string[]
  ) {
    const orderIndex =
      new Map(
        orderedIds.map(
          (
            itemId,
            index
          ) => [
            itemId,
            index + 1,
          ]
        )
      );

    setDraftTimelineItems(
      timelineItems.map(
        (item) =>
          item.dayNumber ===
            activeDayNumber &&
          orderIndex.has(
            item.timelineItemId
          )
            ? {
                ...item,

                visitOrder:
                  orderIndex.get(
                    item.timelineItemId
                  )!,
              }
            : item
      )
    );
  }

  const routeDistanceText =
    route
      ? route.totalDistanceMeters >=
        1000
        ? `${(
            route.totalDistanceMeters /
            1000
          ).toFixed(1)} km`
        : `${route.totalDistanceMeters} m`
      : null;

  const routeDurationText =
    route
      ? (() => {
          const totalMinutes =
            Math.ceil(
              route.totalDurationSeconds /
                60
            );

          if (
            totalMinutes <
            60
          ) {
            return `${totalMinutes}분`;
          }

          const hours =
            Math.floor(
              totalMinutes /
                60
            );

          const minutes =
            totalMinutes %
            60;

          if (
            minutes ===
            0
          ) {
            return `${hours}시간`;
          }

          return `${hours}시간 ${minutes}분`;
        })()
      : null;

  const manageableParticipants:
    Participant[] =
    travelMembers
      .filter(
        (member) =>
          !member.isOwner
      )
      .map(
        (member) => ({
          id:
            member.userId,

          name:
            member.nickname ??
            "알 수 없음",

          permission:
            toPermission(
              member.role as
                TravelRole
            ),

          status:
            member.status ===
            "PENDING"
              ? "pending"
              : "accepted",
        })
      );

  return (
    <>
      <DetailLayout
        detailHeader={
          <TripDetailHeader
            onBack={() =>
              router.push(
                "/trips"
              )
            }

            title={
              detail.title
            }

            isEditing={
              isEditingInfo
            }

            titleDraft={
              titleDraft
            }

            onTitleDraftChange={
              setTitleDraft
            }

            canEdit={
              canEditInfo
            }

            onStartEdit={
              startEditInfo
            }

            onSaveEdit={
              saveEditInfo
            }

            onCancelEdit={
              cancelEditInfo
            }

            saveError={
              infoSaveError
            }

            isOwner={
              isOwner
            }

            onDeleteClick={() =>
              setShowDeleteConfirm(
                true
              )
            }

            members={
              travelMembers
            }

            onInviteClick={() =>
              setShowInvite(
                true
              )
            }

            onManageClick={() =>
              setShowManage(
                true
              )
            }

            onLeaveClick={() =>
              setShowLeaveConfirm(
                true
              )
            }

            onWriteReviewClick={() =>
              router.push(
                `/community/write?travelId=${encodeURIComponent(
                  id ?? ""
                )}`
              )
            }

            countries={
              countries
            }

            selectedCountryId={
              selectedCountryId
            }

            onCountryChange={
              handleCountryChangeDraft
            }

            cities={
              cities
            }

            selectedCityId={
              selectedCityId
            }

            onCityChange={(
              value
            ) =>
              setSelectedCityId(
                Number(
                  value
                )
              )
            }

            selectedCountryName={
              selectedCountryName
            }

            selectedCityName={
              selectedCityName
            }

            dateRange={
              dateRange
            }

            onDateRangeChange={
              setDateRange
            }

            showCalendar={
              showCalendar
            }

            onToggleCalendar={() =>
              setShowCalendar(
                (current) =>
                  !current
              )
            }

            onApplyCalendar={() =>
              setShowCalendar(
                false
              )
            }

            companion={
              companion
            }

            onCompanionChange={
              setCompanion
            }

            companionOptions={
              COMPANION_OPTIONS
            }
          />
        }

        schedule={
          <div className="flex flex-col gap-6">
            <div className="text-lg font-bold text-foreground">
              여행계획
            </div>

            <ScheduleBoard
              days={
                dateTabs
              }

              activeDay={
                visibleActiveDay
              }

              onDayChange={
                handleDayChange
              }

              items={
                activeDayItems
              }

              unassigned={
                unassignedPlaces
              }

              map={
                <div className="flex flex-col gap-2">
                  <MapPanel
                    markers={
                      mapMarkers
                    }

                    encodedPolylines={
                      route?.encodedPolylines ??
                      []
                    }

                    onMarkerClick={
                      handleMapMarkerClick
                    }

                    onOptimizeRoute={
                      handleOptimizeRoute
                    }

                    onSearchNearby={
                      canEditSchedule
                        ? handleSearchNearby
                        : undefined
                    }

                    nearbySearchDisabled={
                      placeSearchLoading
                    }

                    mapSearchQuery={
                      mapSearchQuery
                    }

                    onMapSearchQueryChange={
                      setMapSearchQuery
                    }

                    onMapSearchSubmit={
                      handleMapSearchSubmit
                    }

                    onClearMapSearch={
                      handleClearMapSearch
                    }

                    mapSearchResults={
                      mapSearchResults
                    }

                    mapSearchLoading={
                      mapSearchLoading
                    }

                    mapSearchError={
                      mapSearchError
                    }

                    onMapSearchResultSelect={
                      handleSelectMapSearchResult
                    }

                    selectedPlaceDetail={
                      selectedMapPlace
                    }

                    onAddSelectedPlace={
                      canEditSchedule
                        ? handleAddSelectedMapPlace
                        : undefined
                    }

                    onCloseSelectedPlace={() =>
                      setSelectedMapPlace(
                        null
                      )
                    }

                    showUnassignedMarkers={
                      showUnassignedMarkers
                    }

                    onToggleUnassignedMarkers={() =>
                      setShowUnassignedMarkers(
                        (
                          current
                        ) =>
                          !current
                      )
                    }
                  />

                  {routeLoading && (
                    <p className="text-xs text-muted-foreground">
                      경로 계산 중...
                    </p>
                  )}

                  {route && (
                    <div className="flex flex-wrap gap-3 text-sm text-foreground">
                      {routeDistanceText && (
                        <span>
                          총 이동거리{" "}
                          <strong>
                            {
                              routeDistanceText
                            }
                          </strong>
                        </span>
                      )}

                      {routeDurationText && (
                        <span>
                          예상 이동시간{" "}
                          <strong>
                            {
                              routeDurationText
                            }
                          </strong>
                        </span>
                      )}
                    </div>
                  )}

                  {routeError && (
                    <p className="text-xs text-destructive">
                      {
                        routeError
                      }
                    </p>
                  )}
                </div>
              }

              readOnly={
                !canEditSchedule
              }

              onOpenItem={
                openEditPlace
              }

              onEditItem={
                openEditPlace
              }

              onCancelItem={
                handleCancelItem
              }

              onDeleteItem={
                handleDeleteItem
              }

              onAssignPlace={
                openEditPlace
              }

              onReorderItems={
                handleReorderDay
              }
            />

            {canEditSchedule && (
              <Button
                variant="outline"

                className="w-full border-dashed"

                onClick={
                  openAddPlace
                }
              >
                + 목적지 추가
              </Button>
            )}

            <div>
              <div className="mb-2 text-sm font-bold text-foreground">
                여행 설명
              </div>

              {isEditingInfo ? (
                <div>
                  <Textarea
                    placeholder="이번 여행에 대해 간단히 소개해보세요"

                    value={
                      description
                    }

                    maxLength={
                      DESCRIPTION_MAX_LENGTH
                    }

                    onChange={(
                      event
                    ) =>
                      setDescription(
                        event.target
                          .value
                      )
                    }

                    className="h-[90px]"
                  />

                  <p className="mt-1 text-xs text-muted-foreground">
                    {
                      description.length
                    }
                    /
                    {
                      DESCRIPTION_MAX_LENGTH
                    }
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {description ||
                    "이번 여행에 대해 간단히 소개해보세요"}
                </p>
              )}
            </div>
          </div>
        }
      />

      <PlaceModal
        open={
          editingPlace !=
            null ||
          addingPlace
        }

        onOpenChange={(
          open
        ) => {
          if (!open) {
            setEditingPlace(
              null
            );

            setAddingPlace(
              false
            );

            clearPlaceSearch();
          }
        }}

        mode={
          editingPlace
            ? "edit"
            : "add"
        }

        title={
          editingPlace
            ? editingPlace.name
            : "목적지 추가"
        }

        name={
          placeDraftName
        }

        onNameChange={(
          value
        ) => {
          setPlaceDraftName(
            value
          );

          setPlaceNameError(
            null
          );
        }}

        nameError={
          placeNameError
        }

        note={
          placeDraftNote
        }

        onNoteChange={
          setPlaceDraftNote
        }

        category={
          placeDraftCategory
        }

        onCategoryChange={
          setPlaceDraftCategory
        }

        foodSubcategory={
          placeDraftFoodSubcategory
        }

        onFoodSubcategoryChange={
          setPlaceDraftFoodSubcategory
        }

        placeQuery={
          placeQuery
        }

        onPlaceQueryChange={
          setPlaceQuery
        }

        placeSearchLoading={
          placeSearchLoading
        }

        placeSearchError={
          placeSearchError
        }

        placeResults={
          placeResults.map(
            (
              result
            ): PlaceSearchResultOption => ({
              placeId:
                result.placeId,

              name:
                result.name,

              latitude:
                result.latitude,

              longitude:
                result.longitude,
            })
          )
        }

        onSelectPlaceResult={(
          result
        ) => {
          setPlaceDraftName(
            result.name
          );

          setPlaceNameError(
            null
          );

          setSelectedGooglePlaceId(
            result.placeId
          );

          setSelectedPlaceCoords({
            lat:
              result.latitude,

            lng:
              result.longitude,
          });

          clearPlaceSearch();
        }}

        dateChips={
          editingPlace
            ? dateChips
            : undefined
        }

        onSelectDateChip={
          handleSelectDateChip
        }

        onSave={
          savePlaceModal
        }

        readOnly={
          !canEditSchedule
        }
      />

      <InviteDialog
        open={
          showInvite
        }

        onOpenChange={(
          open
        ) => {
          setShowInvite(
            open
          );

          if (!open) {
            setInviteNickname(
              ""
            );

            setInvitePermission(
              "read"
            );

            setInviteError(
              null
            );
          }
        }}

        nickname={
          inviteNickname
        }

        onNicknameChange={
          setInviteNickname
        }

        permission={
          invitePermission
        }

        onPermissionChange={
          setInvitePermission
        }

        onInvite={() =>
          handleInvite(() =>
            setShowInvite(
              false
            )
          )
        }

        error={
          inviteError
        }
      />

      <ParticipantManageDialog
        open={
          showManage
        }

        onOpenChange={
          setShowManage
        }

        participants={
          manageableParticipants
        }

        onPermissionChange={
          handleMemberPermissionChange
        }

        onRemove={
          handleRemoveMember
        }
      />

      <ConfirmDialog
        open={
          showDeleteConfirm
        }

        onOpenChange={
          setShowDeleteConfirm
        }

        title="여행일정 삭제"

        description="삭제하면 되돌릴 수 없습니다."

        confirmLabel="삭제하기"

        destructive

        onConfirm={
          handleDeleteTravel
        }
      />

      <ConfirmDialog
        open={
          showLeaveConfirm
        }

        onOpenChange={
          setShowLeaveConfirm
        }

        title="일정을 나가시겠어요?"

        description="다시 참여하려면 초대를 받아야 해요."

        confirmLabel="나가기"

        onConfirm={
          handleLeaveTravel
        }
      />
    </>
  );
}