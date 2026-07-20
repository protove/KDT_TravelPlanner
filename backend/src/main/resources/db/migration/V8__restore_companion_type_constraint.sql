ALTER TABLE planners_table
    DROP CONSTRAINT ck_planners_table_companion_type;

UPDATE planners_table
SET companion_type = 'ETC'
WHERE companion_type = 'GROUP';

ALTER TABLE planners_table
    ADD CONSTRAINT ck_planners_table_companion_type CHECK (
        companion_type IS NULL
        OR companion_type IN ('SOLO', 'COUPLE', 'FAMILY', 'FRIEND', 'PET', 'ETC')
    );
