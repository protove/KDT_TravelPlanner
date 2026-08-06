CREATE TABLE planner_purposes (
    id         UUID PRIMARY KEY,
    planner_id UUID NOT NULL REFERENCES planners_table (id) ON DELETE CASCADE,
    purpose    VARCHAR(30) NOT NULL,
    CONSTRAINT uq_planner_purposes_planner_purpose UNIQUE (planner_id, purpose),
    CONSTRAINT ck_planner_purposes_value CHECK (
        purpose IN ('REST_NATURE', 'SIGHTSEEING', 'FOOD', 'ACTIVITY', 'SHOPPING', 'ETC')
    )
);

CREATE INDEX idx_planner_purposes_planner ON planner_purposes (planner_id);
