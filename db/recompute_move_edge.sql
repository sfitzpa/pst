-- recompute_move_edge.sql
-- Updates weight for all move_edge records based on frequency and timestamp.
UPDATE move_edge
SET weight = 1 - exp(-0.15 * GREATEST(freq,1)),
    last_seen = now()
WHERE TRUE;
