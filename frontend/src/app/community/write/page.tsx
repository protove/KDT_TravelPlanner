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
import { RichTextEditor } from "@/components/organisms/RichTextEditor";
import { ListLayout } from "@/components/templates/ListLayout";
import { createPost, getCategories } from "@/lib/api/community";
import { fetchTravelDetail, type TravelDetail } from "@/lib/api/travel";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import type { CommunityCategory, TiptapDocument } from "@/lib/types/community";
import { travelToBodyJson } from "@/lib/utils/travelToBodyJson";
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
  // bodyJson은 "이 일정으로 후기 쓰기" 클릭 시 travelToBodyJson으로 1회만 생성되고,
  // 이후엔 여기 상태만 갱신되는 순수 에디터 상태다 — travel 재조회로 덮어쓰지 않는다.
  const [bodyJson, setBodyJson] = React.useState<TiptapDocument>(EMPTY_BODY_JSON);
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
    getCategories(accessToken)
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

  // 우측 참고 패널 전용 콘텐츠 — 에디터 상태(bodyJson)와 별개로, 조회된 일정이 바뀌면
  // 그대로 다시 계산돼도 안전하다(읽기 전용이라 사용자가 쓴 본문을 덮어쓸 위험이 없음).
  const referenceBodyJson = React.useMemo(() => (travel ? travelToBodyJson(travel) : null), [travel]);

  function handleAutoFill() {
    if (!travel || hasAutoFilled) return;
    setBodyJson(travelToBodyJson(travel));
    setTitle((prev) => prev || `${travel.title} 여행 후기`);
    setCategoryCode(TRAVEL_REVIEW_CATEGORY_CODE);
    setHasAutoFilled(true);
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
      title={<h1 className="text-2xl font-bold text-foreground">여행후기 작성</h1>}
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
            <Button type="button" size="sm" className="ml-auto" onClick={handleAutoFill}>
              이 일정으로 후기 쓰기
            </Button>
          )}
        </div>
      )}

      {travelError && (
        <p role="alert" className="mb-6 text-sm text-destructive-text">
          {travelError}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
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
                  if (e.key === "Enter") {
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

        {travel && referenceBodyJson && (
          <aside className="h-fit lg:sticky lg:top-6">
            <div className="rounded-xl border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-bold text-foreground">일정 참고</h2>
              <div className="max-h-[70vh] overflow-y-auto pr-1">
                <RichTextEditor value={referenceBodyJson} onChange={() => {}} readOnly />
              </div>
            </div>
          </aside>
        )}
      </div>
    </ListLayout>
  );
}
