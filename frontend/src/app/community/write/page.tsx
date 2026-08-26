"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { X } from "lucide-react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { Input } from "@/components/atoms/Input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/atoms/Select";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { FormField } from "@/components/molecules/FormField";
import { ItinerarySnapshotCard } from "@/components/organisms/ItinerarySnapshotCard";
import { RichTextEditor } from "@/components/organisms/RichTextEditor";
import { ListLayout } from "@/components/templates/ListLayout";
import { createPost, getCategories } from "@/lib/api/community";
import { fetchTravelDetail, type TravelDetail } from "@/lib/api/travel";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import type { CommunityCategory, ItinerarySnapshot, TiptapDocument } from "@/lib/types/community";
import { travelToBodyJson } from "@/lib/utils/travelToBodyJson";
import { travelToItinerarySnapshot } from "@/lib/utils/travelToItinerarySnapshot";
import { TITLE_MAX_LENGTH } from "@/lib/validation/text";

const EMPTY_BODY_JSON: TiptapDocument = { type: "doc", content: [{ type: "paragraph" }] };
const TRAVEL_REVIEW_CATEGORY_CODE = "TRAVEL_REVIEW";
const MAX_TAGS = 5;
const TAG_MAX_LENGTH = 20;

export default function CommunityWritePage() {
  return (
    <React.Suspense fallback={null}>
      <CommunityWriteContent />
    </React.Suspense>
  );
}

function CommunityWriteContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const travelId = searchParams.get("travelId") ?? undefined;

  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  const [categoryCode, setCategoryCode] = React.useState(travelId ? TRAVEL_REVIEW_CATEGORY_CODE : "");
  const [title, setTitle] = React.useState("");
  const [tags, setTags] = React.useState<string[]>([]);
  const [tagInput, setTagInput] = React.useState("");
  // bodyJson은 자유 작성 영역 상태. "이 일정으로 후기 쓰기" 클릭 시 travelToBodyJson으로
  // 일정 내용(제목/날짜별 목록)이 편집 가능한 시작 텍스트로 한 번 프리필된다 — 위의 읽기전용
  // 스냅샷 카드와 내용은 같지만, 여긴 그 이후로 사용자가 자유롭게 고쳐 쓸 수 있는 영역이다.
  const [bodyJson, setBodyJson] = React.useState<TiptapDocument>(EMPTY_BODY_JSON);
  // "이 일정으로 후기 쓰기" 클릭 시 travelToItinerarySnapshot으로 1회만 생성되는 읽기전용 일정
  // 스냅샷 — Tiptap 문서가 아니라 일정 자체의 원래 모양(day별 장소 목록 + 좌표)을 그대로 담는다.
  // 작성 시점에 고정되고(불변), 본문 최상단에 읽기전용 카드로 노출되며 사용자가 수정/삭제할 수 없다.
  const [itinerarySnapshot, setItinerarySnapshot] = React.useState<ItinerarySnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = React.useState(false);
  const [snapshotError, setSnapshotError] = React.useState<string | null>(null);
  const [hasAutoFilled, setHasAutoFilled] = React.useState(false);

  const [travel, setTravel] = React.useState<TravelDetail | null>(null);
  const [travelError, setTravelError] = React.useState<string | null>(null);

  const [submitting, setSubmitting] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!isInitializing && !isLoggedIn) router.replace("/");
  }, [isInitializing, isLoggedIn, router]);

  React.useEffect(() => {
    if (!accessToken) return;
    // excludeNotice: 공지사항은 관리자 전용 플로우 대상이라 글쓰기 화면에서는 서버 조회
    // 단계에서부터 아예 로드하지 않는다. 그 외 활성 카테고리(여행후기/자유/QNA 등)는
    // community_category 테이블 값 그대로 선택지에 노출한다.
    getCategories(accessToken, { excludeNotice: true })
      .then((res) => {
        setCategories(res);
        setCategoryCode((prev) => prev || res[0]?.code || "");
      })
      .catch(() => {});
  }, [accessToken]);

  React.useEffect(() => {
    if (!accessToken || !travelId) return;
    let isCurrentRequest = true;

    fetchTravelDetail(accessToken, travelId)
      .then((detail) => {
        if (!isCurrentRequest) return;
        setTravel(detail);
        setTravelError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setTravelError("일정 정보를 불러오지 못했습니다.");
      });

    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, travelId]);

  // day별로 /map-points를 호출해 좌표까지 이 시점 값으로 얼려야 해서 비동기다(day 수만큼
  // 요청이 나간다). 실패해도(좌표 조회 일부 실패 등) travelToItinerarySnapshot 내부에서
  // 개별 day 단위로 흡수하므로, 여기서 잡는 에러는 travel 자체 접근 문제 같은 예외적인 경우다.
  async function handleAutoFill() {
    if (!travel || hasAutoFilled || snapshotLoading || !accessToken) return;
    setSnapshotLoading(true);
    setSnapshotError(null);
    try {
      const snapshot = await travelToItinerarySnapshot(accessToken, travel);
      setItinerarySnapshot(snapshot);
      setBodyJson(travelToBodyJson(travel));
      setTitle((prev) => prev || `${travel.title} 여행 후기`);
      setCategoryCode(TRAVEL_REVIEW_CATEGORY_CODE);
      setHasAutoFilled(true);
    } catch {
      setSnapshotError("일정 스냅샷을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSnapshotLoading(false);
    }
  }

  function handleAddTag() {
    const next = tagInput.trim();
    if (!next || next.length > TAG_MAX_LENGTH) return;
    if (tags.length >= MAX_TAGS || tags.includes(next)) return;
    setTags((prev) => [...prev, next]);
    setTagInput("");
  }

  function handleRemoveTag(tag: string) {
    setTags((prev) => prev.filter((t) => t !== tag));
  }

  async function handleSubmit() {
    if (!accessToken || !categoryCode || !title.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createPost(accessToken, {
        categoryCode,
        title: title.trim(),
        bodyJson,
        tags: tags.length > 0 ? tags : undefined,
        sourceTravelId: travel?.travelId,
        itinerarySnapshotJson: itinerarySnapshot ?? undefined,
      });
      router.push("/community");
    } catch {
      setSubmitError("게시글을 등록하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setSubmitting(false);
    }
  }

  if (isInitializing || !isLoggedIn) return null;

  const canSubmit = Boolean(categoryCode) && title.trim().length > 0 && !submitting;

  return (
    <ListLayout
      title={<h1 className="text-2xl font-bold text-foreground">글쓰기</h1>}
      actions={
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" onClick={() => router.push("/community")}>
            취소
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "등록 중..." : "등록"}
          </Button>
        </div>
      }
    >
      {travel && (
        <div className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-4">
          <Badge variant="secondary">{travel.title}</Badge>
          <DateRangeBadge start={new Date(travel.startDate)} end={new Date(travel.endDate)} />
          <Badge variant="outline">{travel.travelDays}일 일정</Badge>
          {travel.participantCount != null && (
            <Badge variant="outline">참여자 {travel.participantCount}명</Badge>
          )}
          {!hasAutoFilled && (
            <Button
              type="button"
              size="sm"
              className="ml-auto"
              onClick={handleAutoFill}
              disabled={snapshotLoading}
            >
              {snapshotLoading ? "불러오는 중..." : "이 일정으로 후기 쓰기"}
            </Button>
          )}
        </div>
      )}

      {travelError && (
        <p role="alert" className="mb-6 text-sm text-destructive-text">
          {travelError}
        </p>
      )}

      {snapshotError && (
        <p role="alert" className="mb-6 text-sm text-destructive-text">
          {snapshotError}
        </p>
      )}

      <div className="flex flex-col gap-5">
        <FormField label="카테고리" htmlFor="write-category" required>
          <Select value={categoryCode} onValueChange={setCategoryCode}>
            <SelectTrigger id="write-category">
              <SelectValue placeholder="카테고리 선택" />
            </SelectTrigger>
            <SelectContent>
              {categories.map((category) => (
                <SelectItem key={category.code} value={category.code}>
                  {category.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        <FormField label="제목" htmlFor="write-title" required>
          <Input
            id="write-title"
            value={title}
            maxLength={TITLE_MAX_LENGTH}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="제목을 입력하세요"
          />
        </FormField>

        {itinerarySnapshot && (
          <div className="rounded-xl border border-border bg-card p-4">
            <ItinerarySnapshotCard snapshot={itinerarySnapshot} />
          </div>
        )}

        <FormField label="내용" required>
          <RichTextEditor
            value={bodyJson}
            onChange={setBodyJson}
            placeholder="여행 이야기를 자유롭게 남겨보세요"
          />
        </FormField>

        <FormField label="태그" description={`최대 ${MAX_TAGS}개, 태그당 ${TAG_MAX_LENGTH}자 이내`}>
          <div className="flex gap-2">
            <Input
              value={tagInput}
              maxLength={TAG_MAX_LENGTH}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                // 한글/일본어/중국어 IME 조합 중 Enter는 "글자 확정"이지 "태그 추가"가 아니다.
                // isComposing 체크 없이 처리하면 조합 중간 글자가 별도 태그로 잘못 들어간다
                // (예: "도쿄" 입력 중 Enter 두 번 발화되어 "도쿄"와 "쿄"가 따로 추가됨).
                if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  handleAddTag();
                }
              }}
              placeholder="태그 입력 후 Enter"
              disabled={tags.length >= MAX_TAGS}
            />
            <Button
              type="button"
              variant="outline"
              onClick={handleAddTag}
              disabled={tags.length >= MAX_TAGS}
            >
              추가
            </Button>
          </div>
          {tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="gap-1">
                  #{tag}
                  <button
                    type="button"
                    onClick={() => handleRemoveTag(tag)}
                    aria-label={`${tag} 태그 삭제`}
                  >
                    <Icon icon={X} size="sm" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
        </FormField>

        {submitError && (
          <p role="alert" className="text-sm text-destructive-text">
            {submitError}
          </p>
        )}
      </div>
    </ListLayout>
  );
}
