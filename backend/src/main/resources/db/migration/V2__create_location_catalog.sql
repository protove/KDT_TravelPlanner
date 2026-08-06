CREATE TABLE country_table (
    id SMALLINT PRIMARY KEY,
    code CHAR(2) NOT NULL,
    name_ko VARCHAR(50) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    display_order SMALLINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_country_table_code UNIQUE (code),
    CONSTRAINT ck_country_table_code CHECK (code ~ '^[A-Z]{2}$'),
    CONSTRAINT ck_country_table_name_ko CHECK (btrim(name_ko) <> ''),
    CONSTRAINT ck_country_table_name_en CHECK (btrim(name_en) <> ''),
    CONSTRAINT ck_country_table_display_order CHECK (display_order >= 0)
);

CREATE INDEX idx_country_table_active_order
    ON country_table (is_active, display_order, id);

CREATE TABLE city_table (
    id BIGINT PRIMARY KEY,
    country_id SMALLINT NOT NULL,
    name_ko VARCHAR(100) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    google_place_id VARCHAR(255),
    latitude NUMERIC(9, 6),
    longitude NUMERIC(10, 6),
    display_order SMALLINT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT fk_city_table_country FOREIGN KEY (country_id)
        REFERENCES country_table (id) ON DELETE RESTRICT,
    CONSTRAINT uq_city_table_country_name_en UNIQUE (country_id, name_en),
    CONSTRAINT ck_city_table_name_ko CHECK (btrim(name_ko) <> ''),
    CONSTRAINT ck_city_table_name_en CHECK (btrim(name_en) <> ''),
    CONSTRAINT ck_city_table_latitude CHECK (latitude BETWEEN -90 AND 90 OR latitude IS NULL),
    CONSTRAINT ck_city_table_longitude CHECK (longitude BETWEEN -180 AND 180 OR longitude IS NULL),
    CONSTRAINT ck_city_table_display_order CHECK (display_order >= 0)
);

CREATE INDEX idx_city_table_country_active_order
    ON city_table (country_id, is_active, display_order, id);
