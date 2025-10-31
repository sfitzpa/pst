\set min_weight :min_weight  -- provided by -v min_weight=..., defaults if already set

WITH h AS (
  SELECT ch_a, ch_b, s_sent, t_sent, AVG(weight) w_h
  FROM curvature_multi
  WHERE domain='handey'
  GROUP BY ch_a, ch_b, s_sent, t_sent
),
p AS (
  SELECT ch_a, ch_b, s_sent, t_sent, AVG(weight) w_p
  FROM curvature_multi
  WHERE domain='proverbs'
  GROUP BY ch_a, ch_b, s_sent, t_sent
),
pairs AS (
  SELECT h.ch_a, h.ch_b, h.s_sent, h.t_sent, h.w_h, p.w_p,
         0.5 + 0.5 * LEAST(h.w_h, p.w_p) AS conf
  FROM h JOIN p USING (ch_a, ch_b, s_sent, t_sent)
)
INSERT INTO truth (claim, method, evidence, confidence, source)
SELECT
  'Cross-domain curvature conserved: '||ch_a||' + '||ch_b||
  ' at boundary '||s_sent||'→'||t_sent||' (Handey ↔ Proverbs)',
  'cross-domain multi-channel curvature',
  jsonb_build_object(
    'ch_a', ch_a, 'ch_b', ch_b,
    'boundary', s_sent||'→'||t_sent,
    'w_handey', w_h, 'w_proverbs', w_p
  ),
  conf,
  'PST EE Auto-Promoter (Rule B•channels)'
FROM pairs
WHERE w_h >= :min_weight AND w_p >= :min_weight
ON CONFLICT DO NOTHING;
