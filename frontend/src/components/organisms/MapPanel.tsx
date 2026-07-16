"use client";

import * as React from "react";
import { MapPin } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";

export interface MapMarker {
  id: string;
  name: string;
  /** 0~100, 지도 자리 안에서의 상대 위치. 실 지도 연동 전까지의 더미 좌표. */
  x: number;
  y: number;
}

export interface MapPanelProps {
  markers?: MapMarker[];
  onMarkerClick?: (id: string) => void;
  onOptimizeRoute?: () => void;
  className?: string;
}

/**
 * 실 지도 SDK(Google Maps 등) 연동 전 자리표시자.
 * Canvas.dc.html 목업이 비어 있어 연동 방식이 아직 정해지지 않았음 — 결정되면 이 컴포넌트 내부만 교체한다.
 */
function MapPanel({ markers = [], onMarkerClick, onOptimizeRoute, className }: MapPanelProps) {
  return (
    <div className={cn("relative min-h-[320px] w-full overflow-hidden rounded-xl bg-muted shadow-card", className)}>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-xs text-muted-foreground">
        [ 지도 영역 준비 중 ]
      </div>

      {markers.map((marker) => (
        <button
          key={marker.id}
          type="button"
          title={marker.name}
          onClick={() => onMarkerClick?.(marker.id)}
          style={{ left: `${marker.x}%`, top: `${marker.y}%` }}
          className="absolute -translate-x-1/2 -translate-y-full text-primary hover:text-primary/80"
        >
          <Icon icon={MapPin} size="lg" aria-label={marker.name} />
        </button>
      ))}

      <Button size="sm" onClick={onOptimizeRoute} className="absolute right-3 top-3">
        경로 최적화
      </Button>
    </div>
  );
}

export { MapPanel };
