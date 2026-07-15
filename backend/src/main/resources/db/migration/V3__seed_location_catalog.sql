INSERT INTO country_table (
    id,
    code,
    name_ko,
    name_en,
    display_order,
    is_active
) VALUES (
    1,
    'JP',
    '일본',
    'Japan',
    0,
    TRUE
);

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
) VALUES (
    10,
    1,
    '도쿄',
    'Tokyo',
    NULL,
    NULL,
    NULL,
    0,
    TRUE
);
