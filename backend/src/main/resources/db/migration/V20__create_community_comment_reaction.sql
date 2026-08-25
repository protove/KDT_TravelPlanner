CREATE TABLE community_comment_reaction (
    comment_id UUID NOT NULL,
    user_id UUID NOT NULL,
    type VARCHAR(20) NOT NULL,
    CONSTRAINT pk_community_comment_reaction PRIMARY KEY (comment_id, user_id, type),
    CONSTRAINT fk_community_comment_reaction_comment FOREIGN KEY (comment_id)
        REFERENCES community_comment (id) ON DELETE CASCADE,
    CONSTRAINT fk_community_comment_reaction_user FOREIGN KEY (user_id)
        REFERENCES user_table (id) ON DELETE CASCADE,
    CONSTRAINT ck_community_comment_reaction_type CHECK (type IN ('LIKE'))
);

CREATE INDEX idx_community_comment_reaction_user
    ON community_comment_reaction (user_id);
