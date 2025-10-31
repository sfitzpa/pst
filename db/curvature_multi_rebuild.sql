DROP TABLE IF EXISTS curvature_multi;

CREATE TABLE curvature_multi AS
SELECT
  e1.id  AS edge_a,
  e2.id  AS edge_b,
  e1.source_move AS src_a,
  e1.target_move AS tgt_a,
  e2.source_move AS src_b,
  e2.target_move AS tgt_b,
  e1.channel     AS ch_a,
  e2.channel     AS ch_b,
  ((e1.weight + e2.weight)/2.0) AS weight,
  m1.domain,
  m1.frame_id    AS frame_a,
  m2.frame_id    AS frame_b
FROM move_edge e1
JOIN move_edge e2
  ON e1.source_move = e2.source_move
 AND e1.target_move = e2.target_move
JOIN move m1 ON m1.id = e1.source_move
JOIN move m2 ON m2.id = e2.source_move
WHERE e1.channel <> e2.channel;

CREATE INDEX IF NOT EXISTS curvature_multi_dom_idx   ON curvature_multi (domain);
CREATE INDEX IF NOT EXISTS curvature_multi_frame_idx ON curvature_multi (frame_a, frame_b);
