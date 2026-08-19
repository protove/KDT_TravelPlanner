CREATE TABLE community_post_tag (
    post_id UUID NOT NULL,
    tag_id BIGINT NOT NULL,
    CONSTRAINT pk_community_post_tag PRIMARY KEY (post_id, tag_id),
    CONSTRAINT fk_community_post_tag_post FOREIGN KEY (post_id)
        REFERENCES community_post (id) ON DELETE CASCADE,
    CONSTRAINT fk_community_post_tag_tag FOREIGN KEY (tag_id)
        REFERENCES community_tag (id) ON DELETE CASCADE
);

CREATE INDEX idx_community_post_tag_tag
    ON community_post_tag (tag_id);
