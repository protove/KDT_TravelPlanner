ALTER TABLE timeline_table
    DROP CONSTRAINT uq_timeline_planner_day_order;

ALTER TABLE timeline_table
    ADD CONSTRAINT uq_timeline_planner_day_order
        UNIQUE (planner_id, day_number, visit_order)
        DEFERRABLE INITIALLY IMMEDIATE;
