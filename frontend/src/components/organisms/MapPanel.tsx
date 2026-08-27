"use client";

import * as React from "react";
import {
  GoogleMap,
  InfoWindowF,
  MarkerF,
  PolylineF,
  useJsApiLoader,
} from "@react-google-maps/api";

import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export interface MapMarker {
  id: string;
  name: string;
  lat: number;
  lng: number;

  kind?:
    | "assigned"
    | "unassigned"
    | "search"
    | "nearby";

  placeId?: string;

  rating?: number | null;

  userRatingCount?: number | null;

  formattedAddress?: string | null;
}

export interface MapPlaceSearchResult {
  placeId: string;
  name: string;
  latitude: number;
  longitude: number;
  rating: number | null;

  userRatingCount?: number | null;

  formattedAddress?: string | null;
}

export interface MapPanelProps {
  markers?: MapMarker[];

  /*
   * 기존 단일 경로 호환.
   */
  encodedPolyline?: string | null;

  /*
   * TRANSIT 구간별 encoded polyline.
   *
   * 예:
   * [
   *   A→B,
   *   B→C,
   *   C→D
   * ]
   */
  encodedPolylines?: string[];

  onMarkerClick?: (
    id: string
  ) => void;

  onOptimizeRoute?: () => void;

  onSearchNearby?: (
    center: {
      lat: number;
      lng: number;
    }
  ) => void;

  nearbySearchDisabled?: boolean;

  mapSearchQuery?: string;

  onMapSearchQueryChange?: (
    query: string
  ) => void;

  onMapSearchSubmit?: () => void;

  onClearMapSearch?: () => void;

  mapSearchResults?: MapPlaceSearchResult[];

  mapSearchLoading?: boolean;

  mapSearchError?: string | null;

  onMapSearchResultSelect?: (
    place: MapPlaceSearchResult
  ) => void;

  selectedPlaceDetail?:
    | MapPlaceSearchResult
    | null;

  onAddSelectedPlace?: () => void;

  onCloseSelectedPlace?: () => void;

  showUnassignedMarkers?: boolean;

  onToggleUnassignedMarkers?: () => void;

  className?: string;
}

interface LoadedPlaceDetail {
  name: string | null;

  rating: number | null;

  userRatingCount: number | null;

  formattedAddress: string | null;
}

const GOOGLE_MAPS_API_KEY =
  process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ??
  "";

const GOOGLE_MAPS_LIBRARIES:
  "geometry"[] = [
    "geometry",
  ];

const DEFAULT_CENTER = {
  lat: 37.5665,
  lng: 126.978,
};

const MAP_CONTAINER_STYLE:
  React.CSSProperties = {
    width: "100%",
    height: "100%",
  };

const MAP_OPTIONS:
  google.maps.MapOptions = {
    streetViewControl: false,

    mapTypeControl: false,

    fullscreenControl: false,

    clickableIcons: false,
  };

function MapPanel({
  markers = [],

  encodedPolyline = null,

  encodedPolylines = [],

  onMarkerClick,

  onOptimizeRoute,

  onSearchNearby,

  nearbySearchDisabled = false,

  mapSearchQuery = "",

  onMapSearchQueryChange,

  onMapSearchSubmit,

  onClearMapSearch,

  mapSearchResults = [],

  mapSearchLoading = false,

  mapSearchError,

  onMapSearchResultSelect,

  selectedPlaceDetail,

  onAddSelectedPlace,

  onCloseSelectedPlace,

  showUnassignedMarkers = true,

  onToggleUnassignedMarkers,

  className,
}: MapPanelProps) {
  const {
    isLoaded,
    loadError,
  } =
    useJsApiLoader({
      id:
        "travel-planner-google-maps",

      googleMapsApiKey:
        GOOGLE_MAPS_API_KEY,

      libraries:
        GOOGLE_MAPS_LIBRARIES,
    });

  const mapRef =
    React.useRef<
      google.maps.Map | null
    >(null);

  const loadingPlaceIdsRef =
    React.useRef(
      new Set<string>()
    );

  const [
    placeDetailsById,
    setPlaceDetailsById,
  ] =
    React.useState<
      Record<
        string,
        LoadedPlaceDetail
      >
    >({});

  const [
    hoveredMarkerId,
    setHoveredMarkerId,
  ] =
    React.useState<
      string | null
    >(null);

  const [
    pinnedMarkerId,
    setPinnedMarkerId,
  ] =
    React.useState<
      string | null
    >(null);

  const closeMapSearch =
    React.useCallback(() => {
      onClearMapSearch?.();

      onCloseSelectedPlace?.();

      setPinnedMarkerId(
        null
      );

      setHoveredMarkerId(
        null
      );
    }, [
      onClearMapSearch,
      onCloseSelectedPlace,
    ]);

  React.useEffect(() => {
    function handleKeyDown(
      event: KeyboardEvent
    ) {
      if (
        event.key !==
        "Escape"
      ) {
        return;
      }

      closeMapSearch();
    }

    window.addEventListener(
      "keydown",
      handleKeyDown
    );

    return () => {
      window.removeEventListener(
        "keydown",
        handleKeyDown
      );
    };
  }, [
    closeMapSearch,
  ]);

  const hoveredMarker =
    hoveredMarkerId
      ? markers.find(
          (marker) =>
            marker.id ===
            hoveredMarkerId
        ) ?? null
      : null;

  const pinnedMarker =
    pinnedMarkerId
      ? markers.find(
          (marker) =>
            marker.id ===
            pinnedMarkerId
        ) ?? null
      : null;

  const visibleMarker =
    pinnedMarker ??
    hoveredMarker;

  const loadedVisibleDetail =
    visibleMarker?.placeId
      ? placeDetailsById[
          visibleMarker.placeId
        ]
      : undefined;

  const visibleMarkerName =
    loadedVisibleDetail
      ?.name ??
    visibleMarker?.name ??
    "";

  const visibleMarkerRating =
    loadedVisibleDetail
      ?.rating ??
    visibleMarker?.rating ??
    null;

  const visibleMarkerReviewCount =
    loadedVisibleDetail
      ?.userRatingCount ??
    visibleMarker
      ?.userRatingCount ??
    null;

  const visibleMarkerAddress =
    loadedVisibleDetail
      ?.formattedAddress ??
    visibleMarker
      ?.formattedAddress ??
    null;

  async function loadPlaceDetail(
    marker: MapMarker
  ) {
    const placeId =
      marker.placeId;

    if (!placeId) {
      return;
    }

    if (
      placeDetailsById[
        placeId
      ]
    ) {
      return;
    }

    if (
      loadingPlaceIdsRef.current.has(
        placeId
      )
    ) {
      return;
    }

    loadingPlaceIdsRef.current.add(
      placeId
    );

    try {
      const {
        Place,
      } =
        (await window.google.maps.importLibrary(
          "places"
        )) as google.maps.PlacesLibrary;

      const place =
        new Place({
          id:
            placeId,

          requestedLanguage:
            "ko",
        });

      await place.fetchFields({
        fields: [
          "displayName",
          "rating",
          "userRatingCount",
          "formattedAddress",
        ],
      });

      setPlaceDetailsById(
        (current) => ({
          ...current,

          [placeId]: {
            name:
              place.displayName ??
              null,

            rating:
              place.rating ??
              null,

            userRatingCount:
              place.userRatingCount ??
              null,

            formattedAddress:
              place.formattedAddress ??
              null,
          },
        })
      );
    } catch (
      error
    ) {
      console.error(
        "Google Places 상세정보를 불러오지 못했습니다.",
        error
      );
    } finally {
      loadingPlaceIdsRef.current.delete(
        placeId
      );
    }
  }

  /*
   * ======================================================
   * TRANSIT Polyline 디코딩
   * ======================================================
   */

  const routePaths =
    React.useMemo(() => {
      if (
        !isLoaded ||
        !window.google?.maps
          ?.geometry?.encoding
      ) {
        return [];
      }

      /*
       * 새 TRANSIT 배열이 있으면 배열을 사용하고,
       * 없으면 기존 encodedPolyline으로 fallback.
       */
      const routePolylineValues =
        encodedPolylines.length >
        0
          ? encodedPolylines
          : encodedPolyline
            ? [
                encodedPolyline,
              ]
            : [];

      return routePolylineValues
        .filter(
          (value) =>
            value.trim().length >
            0
        )
        .map(
          (value) =>
            window.google.maps.geometry.encoding.decodePath(
              value
            )
        );
    }, [
      isLoaded,
      encodedPolyline,
      encodedPolylines,
    ]);

  const fitToMarkers =
    React.useCallback(() => {
      const map =
        mapRef.current;

      if (!map) {
        return;
      }

      const fitMarkers =
        markers.filter(
          (marker) =>
            marker.kind ===
            "assigned"
        );

      if (
        fitMarkers.length ===
        0
      ) {
        map.setCenter(
          DEFAULT_CENTER
        );

        map.setZoom(
          12
        );

        return;
      }

      if (
        fitMarkers.length ===
        1
      ) {
        map.setCenter({
          lat:
            fitMarkers[0].lat,

          lng:
            fitMarkers[0].lng,
        });

        map.setZoom(
          15
        );

        return;
      }

      const bounds =
        new window.google.maps.LatLngBounds();

      fitMarkers.forEach(
        (marker) => {
          bounds.extend({
            lat:
              marker.lat,

            lng:
              marker.lng,
          });
        }
      );

      map.fitBounds(
        bounds,
        48
      );
    }, [
      markers,
    ]);

  React.useEffect(() => {
    if (!isLoaded) {
      return;
    }

    fitToMarkers();
  }, [
    isLoaded,
    fitToMarkers,
  ]);

  React.useEffect(() => {
    const map =
      mapRef.current;

    if (
      !isLoaded ||
      !map ||
      !selectedPlaceDetail
    ) {
      return;
    }

    map.panTo({
      lat:
        selectedPlaceDetail.latitude,

      lng:
        selectedPlaceDetail.longitude,
    });

    map.setZoom(
      16
    );
  }, [
    isLoaded,
    selectedPlaceDetail,
  ]);

  function handleSearchNearby() {
    const center =
      mapRef.current
        ?.getCenter();

    if (!center) {
      return;
    }

    onSearchNearby?.({
      lat:
        center.lat(),

      lng:
        center.lng(),
    });
  }

  function handleMapSearchSubmit(
    event:
      React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    onMapSearchSubmit?.();
  }

  function handleMarkerMouseOver(
    marker: MapMarker
  ) {
    setHoveredMarkerId(
      marker.id
    );

    void loadPlaceDetail(
      marker
    );
  }

  function handleMarkerMouseOut(
    markerId: string
  ) {
    setHoveredMarkerId(
      (current) =>
        current ===
        markerId
          ? null
          : current
    );
  }

  function handleMarkerClick(
    marker: MapMarker
  ) {
    setPinnedMarkerId(
      (current) =>
        current ===
        marker.id
          ? null
          : marker.id
    );

    void loadPlaceDetail(
      marker
    );

    onMarkerClick?.(
      marker.id
    );
  }

  function handleCloseMarkerDetail() {
    setPinnedMarkerId(
      null
    );

    setHoveredMarkerId(
      null
    );
  }

  function markerIcon(
    kind: MapMarker["kind"]
  ):
    | google.maps.Symbol
    | undefined {
    if (
      kind ===
      "unassigned"
    ) {
      return {
        path:
          "M0,-48C-13.255,-48-24,-37.255-24,-24C-24,-6 0,16 0,16S24,-6 24,-24C24,-37.255 13.255,-48 0,-48ZM0,-16C-4.418,-16-8,-19.582-8,-24S-4.418,-32 0,-32S8,-28.418 8,-24S4.418,-16 0,-16Z",

        fillColor:
          "#9CA3AF",

        fillOpacity:
          1,

        strokeColor:
          "#6B7280",

        strokeOpacity:
          1,

        strokeWeight:
          1.5,

        scale:
          0.65,

        anchor:
          new window.google.maps.Point(
            0,
            16
          ),
      };
    }

    if (
      kind ===
      "search"
    ) {
      return {
        path:
          window.google.maps
            .SymbolPath
            .CIRCLE,

        fillColor:
          "#2563EB",

        fillOpacity:
          1,

        strokeColor:
          "#FFFFFF",

        strokeOpacity:
          1,

        strokeWeight:
          2,

        scale:
          9,
      };
    }

    if (
      kind ===
      "nearby"
    ) {
      return {
        path:
          window.google.maps
            .SymbolPath
            .CIRCLE,

        fillColor:
          "#10B981",

        fillOpacity:
          1,

        strokeColor:
          "#FFFFFF",

        strokeOpacity:
          1,

        strokeWeight:
          2,

        scale:
          8,
      };
    }

    return undefined;
  }

  return (
    <div
      className={cn(
        "relative min-h-[320px] w-full overflow-hidden rounded-xl bg-muted shadow-card",
        className
      )}
    >
      {!GOOGLE_MAPS_API_KEY ? (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center font-mono text-xs text-muted-foreground">
          지도 API 키가 설정되지 않았어요
          <br />
          (.env의 NEXT_PUBLIC_GOOGLE_MAPS_API_KEY)
        </div>
      ) : loadError ? (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center font-mono text-xs text-destructive">
          지도를 불러오지 못했어요
        </div>
      ) : !isLoaded ? (
        <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-muted-foreground">
          지도 불러오는 중...
        </div>
      ) : (
        <div className="absolute inset-0">
          <GoogleMap
            mapContainerStyle={
              MAP_CONTAINER_STYLE
            }

            center={
              DEFAULT_CENTER
            }

            zoom={
              12
            }

            options={
              MAP_OPTIONS
            }

            onLoad={(
              map
            ) => {
              mapRef.current =
                map;

              fitToMarkers();
            }}

            onUnmount={() => {
              mapRef.current =
                null;
            }}

            onClick={() => {
              closeMapSearch();
            }}
          >
            {markers.map(
              (marker) => (
                <MarkerF
                  key={`${marker.id}:${marker.kind ?? "assigned"}`}

                  position={{
                    lat:
                      marker.lat,

                    lng:
                      marker.lng,
                  }}

                  title={
                    marker.name
                  }

                  icon={markerIcon(
                    marker.kind
                  )}

                  onMouseOver={() =>
                    handleMarkerMouseOver(
                      marker
                    )
                  }

                  onMouseOut={() =>
                    handleMarkerMouseOut(
                      marker.id
                    )
                  }

                  onClick={() =>
                    handleMarkerClick(
                      marker
                    )
                  }
                />
              )
            )}

            {visibleMarker && (
              <InfoWindowF
                position={{
                  lat:
                    visibleMarker.lat,

                  lng:
                    visibleMarker.lng,
                }}

                options={{
                  disableAutoPan:
                    true,

                  pixelOffset:
                    new window.google.maps.Size(
                      0,
                      -36
                    ),
                }}

                onCloseClick={
                  handleCloseMarkerDetail
                }
              >
                <div className="min-w-[220px] max-w-[290px] pr-2 text-left">
                  <div className="text-base font-bold text-neutral-900">
                    {
                      visibleMarkerName
                    }
                  </div>

                  {visibleMarkerRating !=
                    null && (
                    <div className="mt-2 flex items-center gap-1 text-sm">
                      <span className="font-semibold text-neutral-900">
                        {
                          visibleMarkerRating
                        }
                      </span>

                      <span className="text-amber-500">
                        ★
                      </span>
                    </div>
                  )}

                  {visibleMarkerReviewCount !=
                    null && (
                    <div className="mt-1 text-sm text-neutral-600">
                      Google 리뷰{" "}

                      <span className="font-medium text-neutral-800">
                        {visibleMarkerReviewCount.toLocaleString(
                          "ko-KR"
                        )}
                      </span>
                    </div>
                  )}

                  {visibleMarkerAddress && (
                    <div className="mt-2 text-xs leading-5 text-neutral-500">
                      {
                        visibleMarkerAddress
                      }
                    </div>
                  )}

                  {!visibleMarker.placeId &&
                    visibleMarkerRating ==
                      null &&
                    visibleMarkerReviewCount ==
                      null &&
                    !visibleMarkerAddress && (
                      <div className="mt-2 text-xs text-neutral-500">
                        Google 장소 상세정보가 연결되지 않은 장소입니다.
                      </div>
                    )}
                </div>
              </InfoWindowF>
            )}

            {/*
             * TRANSIT 구간별 경로를 각각 그린다.
             *
             * A→B
             * B→C
             * C→D
             */}
            {routePaths.map(
              (
                routePath,
                index
              ) => (
                <PolylineF
                  key={
                    `route-segment-${index}`
                  }

                  path={
                    routePath
                  }

                  options={{
                    strokeColor:
                      "#7C3AED",

                    strokeOpacity:
                      0.9,

                    strokeWeight:
                      5,

                    zIndex:
                      1,
                  }}
                />
              )
            )}
          </GoogleMap>
        </div>
      )}

      {onMapSearchSubmit && (
        <div className="absolute left-3 top-3 z-10 w-[min(320px,calc(100%-24px))]">
          <form
            className="flex overflow-hidden rounded-lg border border-border bg-background shadow-card"

            onSubmit={
              handleMapSearchSubmit
            }
          >
            <input
              type="search"

              value={
                mapSearchQuery
              }

              onChange={(
                event
              ) => {
                const value =
                  event.target.value;

                onMapSearchQueryChange?.(
                  value
                );

                if (
                  value.trim() ===
                  ""
                ) {
                  closeMapSearch();
                }
              }}

              placeholder="지도에서 장소 검색"

              className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm outline-none"
            />

            <button
              type="submit"

              disabled={
                mapSearchLoading
              }

              className="cursor-pointer px-3 text-sm font-medium text-primary disabled:cursor-not-allowed disabled:text-muted-foreground"
            >
              검색
            </button>
          </form>

          {(mapSearchResults.length >
            0 ||
            mapSearchError ||
            mapSearchLoading) && (
            <div className="mt-2 max-h-[220px] overflow-auto rounded-lg border border-border bg-background p-1 shadow-card">
              {mapSearchLoading && (
                <div className="px-3 py-2 text-sm text-muted-foreground">
                  검색 중...
                </div>
              )}

              {mapSearchError &&
                !mapSearchLoading && (
                  <div className="px-3 py-2 text-sm text-destructive">
                    {
                      mapSearchError
                    }
                  </div>
                )}

              {!mapSearchLoading &&
                mapSearchResults.map(
                  (place) => (
                    <button
                      key={
                        place.placeId
                      }

                      type="button"

                      className="flex w-full cursor-pointer flex-col rounded-md px-3 py-2 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"

                      onClick={() =>
                        onMapSearchResultSelect?.(
                          place
                        )
                      }
                    >
                      <span className="text-sm font-medium text-foreground">
                        {
                          place.name
                        }
                      </span>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {place.rating !=
                          null && (
                          <span>
                            ★{" "}
                            {
                              place.rating
                            }
                          </span>
                        )}

                        {place.userRatingCount !=
                          null && (
                          <span>
                            Google 리뷰{" "}
                            {place.userRatingCount.toLocaleString(
                              "ko-KR"
                            )}
                          </span>
                        )}
                      </div>

                      {place.formattedAddress && (
                        <span className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                          {
                            place.formattedAddress
                          }
                        </span>
                      )}
                    </button>
                  )
                )}
            </div>
          )}
        </div>
      )}

      {selectedPlaceDetail && (
        <div className="absolute bottom-14 left-3 z-10 w-[min(320px,calc(100%-24px))] rounded-xl border border-border bg-background p-4 shadow-card">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-bold text-foreground">
                {
                  selectedPlaceDetail.name
                }
              </div>

              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {selectedPlaceDetail.rating !=
                  null && (
                  <span>
                    ★{" "}
                    {
                      selectedPlaceDetail.rating
                    }
                  </span>
                )}

                {selectedPlaceDetail.userRatingCount !=
                  null && (
                  <span>
                    Google 리뷰{" "}
                    {selectedPlaceDetail.userRatingCount.toLocaleString(
                      "ko-KR"
                    )}
                  </span>
                )}
              </div>

              {selectedPlaceDetail.formattedAddress && (
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {
                    selectedPlaceDetail.formattedAddress
                  }
                </p>
              )}
            </div>

            <button
              type="button"

              className="cursor-pointer text-sm text-muted-foreground hover:text-foreground"

              onClick={
                closeMapSearch
              }

              aria-label="장소 정보 닫기"
            >
              닫기
            </button>
          </div>

          {onAddSelectedPlace && (
            <Button
              size="sm"

              className="mt-3 w-full"

              onClick={
                onAddSelectedPlace
              }
            >
              일정에 추가
            </Button>
          )}
        </div>
      )}

      <div className="absolute bottom-14 right-3 z-10 flex flex-wrap justify-end gap-2">
        {onToggleUnassignedMarkers && (
          <Button
            size="sm"

            variant="outline"

            onClick={() => {
              setPinnedMarkerId(
                null
              );

              setHoveredMarkerId(
                null
              );

              onToggleUnassignedMarkers();
            }}
          >
            {showUnassignedMarkers
              ? "미배정 장소 숨기기"
              : "미배정 장소 보기"}
          </Button>
        )}

        <Button
          size="sm"

          onClick={
            onOptimizeRoute
          }

          disabled={
            !onOptimizeRoute ||
            !isLoaded
          }
        >
          경로 최적화
        </Button>

        {onSearchNearby && (
          <Button
            size="sm"

            variant="outline"

            onClick={
              handleSearchNearby
            }

            disabled={
              nearbySearchDisabled ||
              !isLoaded
            }
          >
            주변 장소 찾기
          </Button>
        )}
      </div>
    </div>
  );
}

export { MapPanel };