"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Heart, MessageCircle } from "lucide-react";
import { Badge } from "@/components/atoms/Badge";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { CommentInput } from "@/components/molecules/CommentInput";
import { CommentRow } from "@/components/molecules/CommentRow";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { ItinerarySnapshotCard } from "@/components/organisms/ItinerarySnapshotCard";
import { RichTextEditor } from "@/components/organisms/RichTextEditor";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import {
  createComment,
  deleteComment,
  getCategories,
  getComments,
  getPost,
  toggleCommentReaction,
  updateComment,
} from "@/lib/api/community";
import type { CommentResponse, CommunityCategory, CommunityPostDetail } from "@/lib/types/community";
import { formatRelativeTime } from "@/lib/utils/formatRelativeTime";
import { COMMENT_MAX_LENGTH } from "@/lib/validation/text";

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
      <CommunityDetailRoute />
    </React.Suspense>
  );
}

// id(게시글)가 바뀌면 화면 상태를 통째로 초기화하기 위해 key로 리마운트시킨다. 이 덕분에
// 댓글을 새로 불러올 때 "로딩 상태를 다시 true로 되돌리는" 처리를, effect 본문에서 동기적으로
// setState하지 않고도(react-hooks/set-state-in-effect) 자연스럽게 해결할 수 있다 — 아래
// CommunityDetailContent의 댓글 목록 effect 주석 참고.
function CommunityDetailRoute() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? undefined;
  return <CommunityDetailContent key={id} />;
}

function CommunityDetailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const id = searchParams.get("id") ?? undefined;
  // community-api-contract.md 2절 — GET /posts/{postId}는 인증 불필요. 로그인 여부와 관계없이
  // 조회 가능해야 하므로 accessToken 유무로 화면 접근을 막지 않는다(비로그인이면 isMine=false로 옴).
  const isInitializing = useAuthStore((s) => s.isInitializing);
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [post, setPost] = React.useState<CommunityPostDetail | null>(null);
  const [categories, setCategories] = React.useState<CommunityCategory[]>([]);
  const [notFound, setNotFound] = React.useState(false);

  const [comments, setComments] = React.useState<CommentResponse[]>([]);
  const [commentsLoading, setCommentsLoading] = React.useState(true);
  const [commentsError, setCommentsError] = React.useState<string | null>(null);
  const [commentInput, setCommentInput] = React.useState("");
  const [commentSubmitting, setCommentSubmitting] = React.useState(false);
  const [commentActionError, setCommentActionError] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<CommentResponse | null>(null);
  const [deletingCommentId, setDeletingCommentId] = React.useState<string | null>(null);
  const [reactionPendingId, setReactionPendingId] = React.useState<string | null>(null);
  const [editSubmittingId, setEditSubmittingId] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!id) return;
    getPost(accessToken, id)
      .then(setPost)
      .catch(() => setNotFound(true));
  }, [accessToken, id]);

  React.useEffect(() => {
    getCategories(accessToken).then(setCategories).catch(() => {});
  }, [accessToken]);

  // 댓글 목록 — 로그인 상태가 바뀌면 각 댓글의 isMine이 달라지므로 accessToken도 의존성에 둔다.
  // id가 바뀌는 경우는 위 CommunityDetailRoute의 key로 컴포넌트 자체가 새로 마운트되므로
  // commentsLoading 초기값(true)이 자동으로 다시 적용된다 — accessToken만 바뀌어 이 effect가
  // 재실행되는 경우엔 이미 보이는 댓글을 유지한 채 조용히 새로고침한다(재로딩 표시로 깜빡이지 않음).
  React.useEffect(() => {
    if (!id) return;
    let isCurrentRequest = true;
    getComments(accessToken, id)
      .then((res) => {
        if (!isCurrentRequest) return;
        setComments(res);
        setCommentsError(null);
      })
      .catch(() => {
        if (!isCurrentRequest) return;
        setCommentsError("댓글을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (isCurrentRequest) setCommentsLoading(false);
      });

    return () => {
      isCurrentRequest = false;
    };
  }, [accessToken, id]);

  async function handleCommentSubmit() {
    const content = commentInput.trim();
    if (!id || !accessToken || !content || commentSubmitting) return;
    setCommentSubmitting(true);
    setCommentActionError(null);
    try {
      const created = await createComment(accessToken, id, { content });
      setComments((prev) => [...prev, created]);
      setCommentInput("");
    } catch {
      setCommentActionError("댓글을 등록하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setCommentSubmitting(false);
    }
  }

  async function handleConfirmDeleteComment() {
    if (!deleteTarget || !accessToken) return;
    setCommentActionError(null);
    setDeletingCommentId(deleteTarget.commentId);
    try {
      await deleteComment(accessToken, deleteTarget.commentId);
      setComments((prev) => prev.filter((c) => c.commentId !== deleteTarget.commentId));
    } catch {
      setCommentActionError("댓글을 삭제하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setDeletingCommentId(null);
    }
  }

  async function handleToggleReaction(commentId: string) {
    if (!accessToken || reactionPendingId) return;
    setReactionPendingId(commentId);
    setCommentActionError(null);
    try {
      const updated = await toggleCommentReaction(accessToken, commentId);
      setComments((prev) => prev.map((c) => (c.commentId === commentId ? updated : c)));
    } catch {
      setCommentActionError("좋아요 처리에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setReactionPendingId(null);
    }
  }

  async function handleEditComment(commentId: string, content: string): Promise<boolean> {
    if (!accessToken) return false;
    setEditSubmittingId(commentId);
    setCommentActionError(null);
    try {
      const updated = await updateComment(accessToken, commentId, { content });
      setComments((prev) => prev.map((c) => (c.commentId === commentId ? updated : c)));
      return true;
    } catch {
      setCommentActionError("댓글을 수정하지 못했습니다. 잠시 후 다시 시도해주세요.");
      return false;
    } finally {
      setEditSubmittingId(null);
    }
  }

  if (isInitializing) return null;
  if (notFound) return null;
  if (!post) return null;

  const categoryName = categories.find((c) => c.code === post.categoryCode)?.name ?? post.categoryCode;
  const commentCountLabel = (commentsLoading ? post.commentCount : comments.length).toLocaleString();

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
              <span>댓글 {commentCountLabel}</span>
            </div>
          </div>
        </div>
      }
      schedule={
        <>
        <div className="flex flex-col gap-4">
          {post.itinerarySnapshotJson && (
            <div className="rounded-xl border border-border bg-card p-4">
              <ItinerarySnapshotCard snapshot={post.itinerarySnapshotJson} />
            </div>
          )}

          <RichTextEditor value={post.bodyJson} onChange={noop} readOnly />

          <div className="flex items-center gap-4 border-y border-border py-3">
            <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
              <Icon icon={Heart} size="sm" />
              {post.reactionCount.toLocaleString()}
            </span>
            <span className="flex items-center gap-1 text-xs font-semibold text-fg-secondary">
              <Icon icon={MessageCircle} size="sm" />
              {commentCountLabel}
            </span>
          </div>

          <div className="flex flex-col gap-4">
            <h2 className="text-sm font-bold text-foreground">댓글 {commentCountLabel}</h2>

            {isLoggedIn ? (
              <CommentInput
                value={commentInput}
                onChange={setCommentInput}
                onSubmit={handleCommentSubmit}
                submitting={commentSubmitting}
                maxLength={COMMENT_MAX_LENGTH}
              />
            ) : (
              <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-border px-3.5 py-2.5 text-[13px] text-fg-muted">
                <span>로그인하면 댓글을 남길 수 있어요.</span>
                <Button type="button" size="sm" variant="outline" onClick={() => router.push("/auth")}>
                  로그인
                </Button>
              </div>
            )}

            {commentActionError && (
              <p role="alert" className="text-sm text-destructive-text">
                {commentActionError}
              </p>
            )}

            <div className="flex flex-col gap-3">
              {commentsLoading ? (
                <p className="py-4 text-center text-sm text-muted-foreground">댓글을 불러오는 중...</p>
              ) : commentsError ? (
                <p role="alert" className="py-4 text-center text-sm text-destructive-text">
                  {commentsError}
                </p>
              ) : comments.length === 0 ? (
                <p className="py-4 text-center text-sm text-muted-foreground">아직 댓글이 없어요.</p>
              ) : (
                comments.map((comment) => (
                  <CommentRow
                    key={comment.commentId}
                    name={comment.authorNickname}
                    avatarImageUrl={comment.authorProfileImageUrl}
                    timeLabel={formatRelativeTime(comment.createdAt)}
                    text={comment.content}
                    edited={comment.updatedAt != null}
                    reactionCount={comment.reactionCount}
                    isReacted={comment.isReacted}
                    onToggleReaction={isLoggedIn ? () => handleToggleReaction(comment.commentId) : undefined}
                    reactionPending={reactionPendingId === comment.commentId}
                    onDelete={comment.isMine ? () => setDeleteTarget(comment) : undefined}
                    deleting={deletingCommentId === comment.commentId}
                    onEdit={comment.isMine ? (content) => handleEditComment(comment.commentId, content) : undefined}
                    editSubmitting={editSubmittingId === comment.commentId}
                    maxLength={COMMENT_MAX_LENGTH}
                  />
                ))
              )}
            </div>
          </div>
        </div>

        <ConfirmDialog
          open={deleteTarget != null}
          onOpenChange={(next) => !next && setDeleteTarget(null)}
          title="댓글을 삭제할까요?"
          description="삭제한 댓글은 다시 볼 수 없어요."
          confirmLabel="삭제"
          destructive
          isConfirming={deletingCommentId != null}
          onConfirm={handleConfirmDeleteComment}
        />
        </>
      }
    />
  );
}
