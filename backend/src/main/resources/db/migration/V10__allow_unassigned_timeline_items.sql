ALTER TABLE timeline_table ALTER COLUMN day_number DROP NOT NULL;
ALTER TABLE timeline_table ALTER COLUMN visit_date DROP NOT NULL;

ALTER TABLE timeline_table ADD CONSTRAINT ck_timeline_day_visit_pair CHECK (
    (day_number IS NULL AND visit_date IS NULL) OR
    (day_number IS NOT NULL AND visit_date IS NOT NULL)
);