"use client";

import * as React from "react";
import { GoogleMap, MarkerF, useJsApiLoader } from "@react-google-maps/api";
import { Button } from "@/components/atoms/Button";
import { cn } from "@/lib/utils";

export interface MapMarker {
  id: string;
  name: string;
  /** 실제 위도/경도. 백엔드 /api/v1/travels/{id}/map-points 응답 기준. */
  lat: number;
  lng: number;
}

export interface MapPanelProps {
  markers?: MapMarker[];
  onMarkerClick?: (id: string) => void;
  onOptimizeRoute?: () => void;
  onSearchNearby?: (center: { lat: number; lng: number }) => void;
  nearbySearchDisabled?: boolean;
  className?: string;
}

const GOOGLE_MAPS_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";

// 마커가 하나도 없을 때(여행지 미정 등) 보여줄 기본 중심 — 서울시청.
const DEFAULT_CENTER = { lat: 37.5665, lng: 126.978 };

const MAP_CONTAINER_STYLE: React.CSSProperties = { width: "100%", height: "100%" };

const MAP_OPTIONS: google.maps.MapOptions = {
  streetViewControl: false,
  mapTypeControl: false,
  fullscreenControl: false,
};

/**
 * Google Maps JavaScript SDK(@react-google-maps/api) 연동.
 * 스크립트 로딩은 useJsApiLoader가 id 기준으로 중복 로드를 막아주지만, 이 패널이
 * 한 화면에 여러 개 동시에 뜨는 경우가 생기면 이 로딩 훅을 상위(Provider)로 올리는 걸 고려할 것.
 * 경로선(Directions/Route) 표시는 아직 없음 — 추가할 때 useJsApiLoader의 libraries에 "geometry"를
 * 넣고 백엔드 /api/v1/travels/{id}/routes의 encodedPolyline을 google.maps.geometry.encoding으로
 * 디코딩해서 Polyline으로 그리면 된다.
 */
function MapPanel({
  markers = [],
  onMarkerClick,
  onOptimizeRoute,
  onSearchNearby,
  nearbySearchDisabled = false,
  className,
}: MapPanelProps) {
  const { isLoaded, loadError } = useJsApiLoader({
    id: "travel-planner-google-maps",
    googleMapsApiKey: GOOGLE_MAPS_API_KEY,
  });
  const mapRef = React.useRef<google.maps.Map | null>(null);

  const fitToMarkers = React.useCallback(() => {
    const map = mapRef.current;
    if (!map || markers.length === 0) return;
    if (markers.length === 1) {
      map.setCenter({ lat: markers[0].lat, lng: markers[0].lng });
      map.setZoom(15);
      return;
    }
    const bounds = new window.google.maps.LatLngBounds();
    markers.forEach((marker) => bounds.extend({ lat: marker.lat, lng: marker.lng }));
    map.fitBounds(bounds, 48);
  }, [markers]);

  // 날짜 탭을 바꾸는 등 markers 자체가 바뀔 때도, 이미 떠 있는 지도의 화면 범위를 다시 맞춘다.
  React.useEffect(() => {
    if (isLoaded) fitToMarkers();
  }, [isLoaded, fitToMarkers]);

  function handleSearchNearby() {
    const center = mapRef.current?.getCenter();
    if (!center) return;
    onSearchNearby?.({ lat: center.lat(), lng: center.lng() });
  }

  return (
    <div className={cn("relative min-h-[320px] w-full overflow-hidden rounded-xl bg-muted shadow-card", className)}>
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
        // 바깥 박스가 min-height라 "height: 100%"만으론 안쪽 지도 높이가 0으로 계산될 수 있어서
        // (부모 높이가 "정해진 값"이 아니라 퍼센트 높이가 안 먹힘), absolute inset-0으로 강제로 꽉 채운다.
        <div className="absolute inset-0">
          <GoogleMap
            mapContainerStyle={MAP_CONTAINER_STYLE}
            center={DEFAULT_CENTER}
            zoom={12}
            options={MAP_OPTIONS}
            onLoad={(map) => {
              mapRef.current = map;
              fitToMarkers();
            }}
            onUnmount={() => {
              mapRef.current = null;
            }}
          >
            {markers.map((marker) => (
              <MarkerF
                key={marker.id}
                position={{ lat: marker.lat, lng: marker.lng }}
                title={marker.name}
                onClick={() => onMarkerClick?.(marker.id)}
              />
            ))}
          </GoogleMap>
        </div>
      )}

      <div className="absolute bottom-3 right-3 flex gap-2">
        {onSearchNearby && (
          <Button size="sm" variant="outline" onClick={handleSearchNearby} disabled={nearbySearchDisabled || !isLoaded}>
            주변 장소 찾기
          </Button>
        )}
        <Button size="sm" onClick={onOptimizeRoute}>
          경로 최적화
        </Button>
      </div>
    </div>
  );
}

export { MapPanel };
