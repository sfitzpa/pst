DROP TABLE IF EXISTS curvature_multi;
CREATE TABLE curvature_multi AS
SELECT
  a.session_id,
  a.domain,
  a.channel AS ch_a,  -- first channel
  b.channel AS ch_b,  -- second channel
  a.s_sent, a.t_sent, -- the shared boundary i -> i+1
  a.delta AS da,
  b.delta AS db,
  ((a.weight + b.weight)/2.0) AS weight
FROM 
(
  SELECT
    e.id, e.channel, e.delta, e.weight,
    ms.session_id, ms.domain,
    (ms.span->>'sent')::int AS s_sent,
    (mt.span->>'sent')::int AS t_sent
  FROM move_edge e
  JOIN move ms ON ms.id = e.source_move
  JOIN move mt ON mt.id = e.target_move
)
a
JOIN 
(
  SELECT
    e.id, e.channel, e.delta, e.weight,
    ms.session_id, ms.domain,
    (ms.span->>'sent')::int AS s_sent,
    (mt.span->>'sent')::int AS t_sent
  FROM move_edge e
  JOIN move ms ON ms.id = e.source_move
  JOIN move mt ON mt.id = e.target_move
)
b
  ON a.session_id = b.session_id
 AND a.domain     = b.domain
 AND a.s_sent     = b.s_sent
 AND a.t_sent     = b.t_sent
 AND a.channel   <> b.channel;
CREATE INDEX IF NOT EXISTS curvature_multi_dom_idx ON curvature_multi (domain);