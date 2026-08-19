CREATE TABLE community_reaction (
    post_id UUID NOT NULL,
    user_id UUID NOT NULL,
    type VARCHAR(20) NOT NULL,
    CONSTRAINT pk_community_reaction PRIMARY KEY (post_id, user_id, type),
    CONSTRAINT fk_community_reaction_post FOREIGN KEY (post_id)
        REFERENCES community_post (id) ON DELETE CASCADE,
    CONSTRAINT fk_community_reaction_user FOREIGN KEY (user_id)
        REFERENCES user_table (id) ON DELETE CASCADE,
    CONSTRAINT ck_community_reaction_type CHECK (type IN ('LIKE'))
);

CREATE INDEX idx_community_reaction_user
    ON community_reaction (user_id);
