"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Heart, MessageCircle } from "lucide-react";
import { Badge } from "@/components/atoms/Badge";
import { Icon } from "@/components/atoms/Icon";
import { RichTextEditor } from "@/components/organisms/RichTextEditor";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { getCategories, getPost } from "@/lib/api/community";
import type { CommunityCategory, CommunityPostDetail } from "@/lib/types/community";

function formatCreatedAt(iso: string): string {
  const date = new Date(iso);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}.${m}.${d}`;
}

function noop() {}

export default function CommunityDetailPage() {
  return (
    <React.Suspense fallback={null}>
      <CommunityDetailContent />
    </React.Suspense>
  );
}

function CommunityDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? undefined;
  // community-api-contract.md 2절 — GET /posts/{postId}는 인증 불필요. 로그인 여부와 관계없이
  // 조회 가능해야 하므로 accessToken 유무로 화면 접근을 막지 않는다(비로그인이면 isMine=false로 옴).
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [post, setPost] = React.useState<CommunityPostDetail | null>(null);
  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  const [notFound, setNotFound] = React.useState(false);

  React.useEffect(() => {
    if (!id) return;
    getPost(accessToken, id)
      .then(setPost)
      .catch(() => setNotFound(true));
  }, [accessToken, id]);

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  if (isInitializing) return null;
  if (notFound) return null;
  if (!post) return null;

  const categoryName = categories.find((c) => c.code === post.categoryCode)?.name ?? post.categoryCode;

  return (
    <DetailLayout
      detailHeader={
        <div className="flex flex-col gap-5">
          <div className="flex items-center gap-2 text-sm text-fg-muted">
            <button
              type="button"
              onClick={() => router.push("/community")}
              className="flex items-center gap-2 hover:text-foreground"
            >
              <Icon icon={ArrowLeft} size="sm" />
              <span>커뮤니티</span>
            </button>
            <span>{">"}</span>
            <span className="font-semibold">{categoryName}</span>
          </div>

          <div className="flex flex-col gap-3">
            <Badge variant="accent" className="w-fit">
              {categoryName}
            </Badge>
            <h1 className="text-2xl font-bold text-foreground">{post.title}</h1>
          </div>

          <div className="flex items-center justify-between border-b border-border pb-3">
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold text-foreground">{post.authorNickname}</span>
              <span className="text-xs text-fg-muted">{formatCreatedAt(post.createdAt)} 작성</span>
            </div>
            <div className="flex items-center gap-3 text-[13px] text-fg-muted">
              <span>조회수 {post.viewCount.toLocaleString()}</span>
              <span>댓글 {post.commentCount.toLocaleString()}</span>
            </div>
          </div>
        </div>
      }
      schedule={
        <div className="flex flex-col gap-4">
          <RichTextEditor value={post.bodyJson} onChange={noop} readOnly />

          <div className="flex items-center gap-4 border-y border-border py-3">
            <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
              <Icon icon={Heart} size="sm" />
              {post.reactionCount.toLocaleString()}
            </span>
            <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
              <Icon icon={MessageCircle} size="sm" />
              {post.commentCount.toLocaleString()}
            </span>
          </div>
        </div>
      }
    />
  );
}
