ALTER TABLE timeline_table
    ALTER COLUMN google_place_id TYPE TEXT,
    DROP CONSTRAINT ck_timeline_latitude,
    DROP CONSTRAINT ck_timeline_longitude,
    DROP CONSTRAINT ck_timeline_rating,
    DROP COLUMN latitude,
    DROP COLUMN longitude,
    DROP COLUMN rating;
