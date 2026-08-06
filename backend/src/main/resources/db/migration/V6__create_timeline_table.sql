CREATE TABLE timeline_table (
    id UUID PRIMARY KEY,
    planner_id UUID NOT NULL,
    day_number SMALLINT NOT NULL,
    visit_date DATE NOT NULL,
    city_id BIGINT,
    category VARCHAR(20) NOT NULL,
    food_subcategory VARCHAR(30),
    name VARCHAR(100) NOT NULL,
    google_place_id VARCHAR(255),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(10, 6),
    rating NUMERIC(2, 1),
    visit_order SMALLINT NOT NULL,
    memo TEXT,
    CONSTRAINT fk_timeline_planner FOREIGN KEY (planner_id)
        REFERENCES planners_table (id) ON DELETE CASCADE,
    CONSTRAINT fk_timeline_city FOREIGN KEY (city_id)
        REFERENCES city_table (id) ON DELETE SET NULL,
    CONSTRAINT uq_timeline_planner_day_order UNIQUE (planner_id, day_number, visit_order),
    CONSTRAINT ck_timeline_day_number CHECK (day_number >= 1),
    CONSTRAINT ck_timeline_visit_order CHECK (visit_order >= 1),
    CONSTRAINT ck_timeline_category CHECK (category IN ('관광지', '음식', '숙소', '교통', '기타')),
    CONSTRAINT ck_timeline_food_subcategory CHECK (food_subcategory IS NULL OR category = '음식'),
    CONSTRAINT ck_timeline_latitude CHECK (latitude BETWEEN -90 AND 90 OR latitude IS NULL),
    CONSTRAINT ck_timeline_longitude CHECK (longitude BETWEEN -180 AND 180 OR longitude IS NULL),
    CONSTRAINT ck_timeline_rating CHECK (rating BETWEEN 0 AND 5 OR rating IS NULL)
);

CREATE INDEX idx_timeline_planner_visit_date_order
    ON timeline_table (planner_id, visit_date, visit_order);
