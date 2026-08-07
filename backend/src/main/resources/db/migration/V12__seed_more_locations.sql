-- 한국인이 많이 가는 인기 여행지 위주로 국가/도시 시드 데이터 추가.
-- V3__seed_location_catalog.sql이 일본(도쿄)만 넣어뒀던 것을 보강한다.
-- 국가/도시 목록은 임시 데이터 — 팀 확인 후 조정 예정.

INSERT INTO country_table (
    id,
    code,
    name_ko,
    name_en,
    display_order,
    is_active
) VALUES
    (2, 'KR', '한국', 'South Korea', 1, TRUE),
    (3, 'TH', '태국', 'Thailand', 2, TRUE),
    (4, 'VN', '베트남', 'Vietnam', 3, TRUE),
    (5, 'TW', '대만', 'Taiwan', 4, TRUE);

INSERT INTO city_table (
    id,
    country_id,
    name_ko,
    name_en,
    google_place_id,
    latitude,
    longitude,
    display_order,
    is_active
) VALUES
    (20, 2, '서울', 'Seoul', NULL, NULL, NULL, 0, TRUE),
    (21, 2, '부산', 'Busan', NULL, NULL, NULL, 1, TRUE),
    (22, 1, '오사카', 'Osaka', NULL, NULL, NULL, 1, TRUE),
    (23, 1, '교토', 'Kyoto', NULL, NULL, NULL, 2, TRUE),
    (24, 3, '방콕', 'Bangkok', NULL, NULL, NULL, 0, TRUE),
    (25, 4, '다낭', 'Da Nang', NULL, NULL, NULL, 0, TRUE),
    (26, 5, '타이베이', 'Taipei', NULL, NULL, NULL, 0, TRUE);
