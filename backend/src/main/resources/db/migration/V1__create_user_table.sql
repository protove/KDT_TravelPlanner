CREATE TABLE user_table (
    id UUID PRIMARY KEY,
    provider VARCHAR(20) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    name VARCHAR(100),
    nickname VARCHAR(30),
    profile_image_url TEXT,
    gender VARCHAR(20),
    birth_year SMALLINT,
    profile_completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uk_user_table_provider_user_id UNIQUE (provider, provider_user_id),
    CONSTRAINT uk_user_table_nickname UNIQUE (nickname),
    CONSTRAINT chk_user_table_provider CHECK (provider IN ('GOOGLE', 'NAVER')),
    CONSTRAINT chk_user_table_gender CHECK (
        gender IS NULL OR gender IN ('MALE', 'FEMALE', 'OTHER', 'UNSPECIFIED')
    ),
    CONSTRAINT chk_user_table_birth_year CHECK (
        birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100
    )
);
