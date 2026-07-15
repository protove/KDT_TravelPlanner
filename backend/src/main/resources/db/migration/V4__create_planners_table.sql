CREATE TABLE planners_table (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    title VARCHAR(100) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    country_id SMALLINT,
    city_id BIGINT,
    companion_type VARCHAR(20),
    companion_count SMALLINT,
    comment TEXT,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_planners_table_owner FOREIGN KEY (owner_id)
        REFERENCES user_table (id) ON DELETE RESTRICT,
    CONSTRAINT fk_planners_table_country FOREIGN KEY (country_id)
        REFERENCES country_table (id) ON DELETE SET NULL,
    CONSTRAINT fk_planners_table_city FOREIGN KEY (city_id)
        REFERENCES city_table (id) ON DELETE SET NULL,
    CONSTRAINT ck_planners_table_title CHECK (btrim(title) <> ''),
    CONSTRAINT ck_planners_table_date_range CHECK (end_date >= start_date),
    CONSTRAINT ck_planners_table_city_country CHECK (city_id IS NULL OR country_id IS NOT NULL),
    CONSTRAINT ck_planners_table_companion_type CHECK (
        companion_type IS NULL OR companion_type IN ('SOLO', 'FRIEND', 'COUPLE', 'FAMILY', 'GROUP')
    ),
    CONSTRAINT ck_planners_table_companion_count CHECK (
        companion_count IS NULL OR companion_count >= 1
    )
);

CREATE INDEX idx_planners_table_owner_active
    ON planners_table (owner_id, updated_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_planners_table_country_city
    ON planners_table (country_id, city_id)
    WHERE deleted_at IS NULL;
