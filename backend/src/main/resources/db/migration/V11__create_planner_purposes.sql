CREATE TABLE planner_purposes (
    planner_id UUID NOT NULL REFERENCES planners_table (id) ON DELETE CASCADE,
    purpose    VARCHAR(30) NOT NULL,
    PRIMARY KEY (planner_id, purpose),
    CONSTRAINT ck_planner_purposes_value CHECK (
        purpose IN ('REST_NATURE', 'SIGHTSEEING', 'FOOD', 'ACTIVITY', 'SHOPPING', 'ETC')
    )
);

CREATE INDEX idx_planner_purposes_planner ON planner_purposes (planner_id);
