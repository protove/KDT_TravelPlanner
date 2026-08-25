-- 댓글 수정 기능 추가 — 수정 시각을 기록한다. NULL이면 한 번도 수정되지 않은 댓글이다.
ALTER TABLE community_comment ADD COLUMN updated_at TIMESTAMPTZ;
