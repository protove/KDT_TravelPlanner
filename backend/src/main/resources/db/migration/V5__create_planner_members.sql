CREATE TABLE planner_members (
    id UUID PRIMARY KEY,
    planner_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    invited_at TIMESTAMPTZ NOT NULL,
    responded_at TIMESTAMPTZ,
    CONSTRAINT fk_planner_members_planner FOREIGN KEY (planner_id)
        REFERENCES planners_table (id) ON DELETE CASCADE,
    CONSTRAINT fk_planner_members_user FOREIGN KEY (user_id)
        REFERENCES user_table (id) ON DELETE CASCADE,
    CONSTRAINT uq_planner_members_planner_user UNIQUE (planner_id, user_id),
    CONSTRAINT ck_planner_members_role CHECK (role IN ('READ_ONLY', 'READ_WRITE')),
    CONSTRAINT ck_planner_members_status CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED'))
);

CREATE INDEX idx_planner_members_user_status_invited
    ON planner_members (user_id, status, invited_at DESC);

CREATE INDEX idx_planner_members_planner_status
    ON planner_members (planner_id, status);
