CREATE TABLE community_post (
    id UUID PRIMARY KEY,
    author_id UUID NOT NULL,
    category_id SMALLINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    body_json JSONB NOT NULL,
    body_preview VARCHAR(200),
    source_travel_id UUID,
    view_count INT NOT NULL DEFAULT 0,
    version INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT fk_community_post_author FOREIGN KEY (author_id)
        REFERENCES user_table (id) ON DELETE CASCADE,
    CONSTRAINT fk_community_post_category FOREIGN KEY (category_id)
        REFERENCES community_category (id) ON DELETE RESTRICT,
    CONSTRAINT fk_community_post_source_travel FOREIGN KEY (source_travel_id)
        REFERENCES planners_table (id) ON DELETE SET NULL,
    CONSTRAINT ck_community_post_title CHECK (btrim(title) <> ''),
    CONSTRAINT ck_community_post_view_count CHECK (view_count >= 0)
);

CREATE INDEX idx_community_post_category_active
    ON community_post (category_id, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_community_post_author_active
    ON community_post (author_id, created_at DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_community_post_source_travel
    ON community_post (source_travel_id)
    WHERE source_travel_id IS NOT NULL;
