-- 여행후기 작성 시점의 일정 스냅샷. source_travel_id로 연결된 원본 여행이 이후 수정/삭제되어도
-- 이 컬럼에 담긴 값은 바뀌지 않는다(작성 시점 고정 스냅샷, live-link 아님).
-- bodyJson과 동일한 TiptapDocument 스키마를 쓰며, 표시 전용(읽기전용) — 사용자가 수정하는 API는 없다.
ALTER TABLE community_post ADD COLUMN itinerary_snapshot_json JSONB;
