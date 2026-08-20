CREATE TABLE community_category (
    id SMALLINT PRIMARY KEY,
    code VARCHAR(30) NOT NULL,
    name VARCHAR(50) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_community_category_code UNIQUE (code),
    CONSTRAINT ck_community_category_code CHECK (btrim(code) <> ''),
    CONSTRAINT ck_community_category_name CHECK (btrim(name) <> ''),
    CONSTRAINT ck_community_category_sort_order CHECK (sort_order >= 0)
);

CREATE INDEX idx_community_category_active_order
    ON community_category (is_active, sort_order, id);

INSERT INTO community_category (id, code, name, sort_order, is_active) VALUES
    (1, 'TRAVEL_REVIEW', '여행후기', 1, TRUE),
    (2, 'FREE', '자유게시판', 2, TRUE),
    (3, 'QNA', '질문답변', 3, TRUE),
    (4, 'NOTICE', '공지사항', 4, TRUE);
