-- Drop/rebuild helper for R3 (can be re-run anytime)
DROP TABLE IF EXISTS curvature;
CREATE TABLE curvature AS
SELECT
  e1.source_id AS a,
  e1.target_id AS b,
  e2.target_id AS c,
  (e1.freq + e2.freq)/2.0 AS freq,
  (e1.weight + e2.weight)/2.0 AS weight,
  COALESCE((e1.context->>'domain'), (e2.context->>'domain')) AS domain
FROM trajectory e1
JOIN trajectory e2 ON e1.target_id = e2.source_id;
CREATE INDEX IF NOT EXISTS curvature_domain_idx ON curvature (domain);