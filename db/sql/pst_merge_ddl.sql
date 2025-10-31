-- =========================
-- PST MERGED DDL (idempotent)
-- =========================

-- 0) Extensions/guards (vector assumed installed already)

-- 1) Root Truth & Frame helpers (you already have both tables)
CREATE OR REPLACE FUNCTION frame_id_by_code(p_code TEXT)
RETURNS INT LANGUAGE sql AS $$
  SELECT id FROM frame WHERE code = p_code
$$;

-- 2) POSIT: link to frame (keep your existing columns)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='posit' AND column_name='frame_id'
  ) THEN
    ALTER TABLE public.posit
      ADD COLUMN frame_id INT REFERENCES public.frame(id);
  END IF;
END $$;

-- 3) Helpful indexes (speed up common queries)
CREATE INDEX IF NOT EXISTS move_frame_idx      ON public."move"(frame_id);
CREATE INDEX IF NOT EXISTS moveedge_frame_idx  ON public.move_edge(frame_id);
CREATE INDEX IF NOT EXISTS cm_frame_pair_idx   ON public.curvature_multi(frame_a, frame_b);
CREATE INDEX IF NOT EXISTS truth_framepair_idx ON public.truth(frame_pair);
CREATE INDEX IF NOT EXISTS posit_author_idx    ON public.posit(author_id);
CREATE INDEX IF NOT EXISTS eval_posit_idx      ON public.evaluation(posit_id);

-- 4) Evidence-driven recompute of move_edge.weight (no wall-clock decay)
CREATE OR REPLACE FUNCTION recompute_move_edge_v2() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  WITH basis AS (
    SELECT
      e.id,
      e.freq,
      ms.session_id,
      (ms.span->>'sent')::int AS s_sent,
      (mt.span->>'sent')::int AS t_sent,
      e.channel
    FROM move_edge e
    JOIN "move" ms ON ms.id = e.source_move
    JOIN "move" mt ON mt.id = e.target_move
  ),
  siblings AS (
    SELECT
      b.*,
      COUNT(*) OVER (PARTITION BY session_id, s_sent, t_sent, channel) AS siblings_cnt
    FROM basis b
  ),
  opp AS (
    -- opposing motion ≈ cosine < 0 (use inner product distance operator <#>)
    SELECT e1.id, COALESCE(SUM( CASE WHEN (e1.delta <#> e2.delta) > 0 THEN 1 ELSE 0 END ),0) AS oppose
    FROM move_edge e1
    JOIN move_edge e2
      ON e1.id <> e2.id
     AND e1.channel = e2.channel
    GROUP BY e1.id
  )
  UPDATE move_edge e
  SET weight = LEAST(1.0,
              (0.60 * (1 - exp(-0.20 * GREATEST(e.freq,1)))) +           -- recurrence
              (0.25 * (1 - exp(-0.50 * GREATEST(s.siblings_cnt-1,0))))   -- local diversity
            ) * exp(-0.30 * COALESCE(o.oppose,0)),                       -- conflict penalty
      last_seen = now()
  FROM siblings s
  LEFT JOIN opp o ON o.id = e.id
  WHERE e.id = s.id;
END $$;

-- 5) Curvature rebuild (derives from move_edge + move; includes frames)
CREATE OR REPLACE FUNCTION rebuild_curvature_multi() RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  DROP TABLE IF EXISTS public.curvature_multi;
  CREATE TABLE public.curvature_multi AS
  SELECT
    ms.session_id,
    ms.domain,
    e1.channel AS ch_a,
    e2.channel AS ch_b,
    (ms.span->>'sent')::int AS s_sent,
    (mt.span->>'sent')::int AS t_sent,
    e1.delta AS da,
    e2.delta AS db,
    ((e1.weight + e2.weight)/2.0) AS weight,
    ms.frame_id AS frame_a,
    ms.frame_id AS frame_b   -- source frames for both edges (same boundary, different channels)
  FROM move_edge e1
  JOIN move_edge e2
    ON e1.source_move = e2.source_move
   AND e1.target_move = e2.target_move
   AND e1.channel <> e2.channel
  JOIN "move" ms ON ms.id = e1.source_move
  JOIN "move" mt ON mt.id = e1.target_move;

  CREATE INDEX IF NOT EXISTS curvature_multi_dom_idx   ON public.curvature_multi (domain);
  CREATE INDEX IF NOT EXISTS curvature_multi_frame_idx ON public.curvature_multi (frame_a, frame_b);
END $$;

-- 6) Cross-domain/channel truth promoter (parameterized threshold), writes into YOUR 'truth'
-- Uses psql -v min_weight=0.30 to pass threshold; defaults to 0.30 if not provided.
-- For server-side calls we wrap with a stable default.
CREATE OR REPLACE FUNCTION promote_cross_domain_curvature(p_min_weight DOUBLE PRECISION DEFAULT 0.30)
RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE ins INT;
BEGIN
  WITH h AS (
    SELECT ch_a, ch_b, s_sent, t_sent, AVG(weight) w_h
    FROM curvature_multi WHERE domain='handey'
    GROUP BY ch_a, ch_b, s_sent, t_sent
  ),
  p AS (
    SELECT ch_a, ch_b, s_sent, t_sent, AVG(weight) w_p
    FROM curvature_multi WHERE domain='proverbs'
    GROUP BY ch_a, ch_b, s_sent, t_sent
  ),
  pairs AS (
    SELECT h.ch_a, h.ch_b, h.s_sent, h.t_sent, h.w_h, p.w_p,
           0.5 + 0.5 * LEAST(h.w_h, p.w_p) AS conf
    FROM h JOIN p USING (ch_a, ch_b, s_sent, t_sent)
    WHERE h.w_h >= p_min_weight AND p.w_p >= p_min_weight
  )
  INSERT INTO public.truth (claim, method, evidence, confidence, source, frame_pair, created_at)
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
    'PST EE Auto-Promoter (Rule B•channels)',
    'handey↔proverbs',
    now()
  FROM pairs
  ON CONFLICT DO NOTHING
  RETURNING 1 INTO ins;
  RETURN COALESCE(ins,0);
END $$;

-- 7) POSIT EVALUATOR v0 writing into YOUR 'evaluation' table (not a new table)
-- 7a. logical_integrity → evaluation.coherence
CREATE OR REPLACE FUNCTION eval_logical_integrity_v0(p_id BIGINT)
RETURNS DOUBLE PRECISION LANGUAGE plpgsql AS $$
DECLARE s TEXT; sc DOUBLE PRECISION := 0.85;
BEGIN
  SELECT statement INTO s FROM public.posit WHERE id = p_id;
  IF s IS NULL THEN RETURN 0.0; END IF;
  IF s ~* '\bnot\b.*\band\b.*\bnot\b' OR s ~* '\bA and not A\b' THEN
    sc := sc - 0.35;
  END IF;
  INSERT INTO public.evaluation(posit_id, coherence, created_at, notes)
  VALUES (p_id, GREATEST(0,LEAST(1,sc)), now(), 'logical_integrity v0');
  RETURN sc;
END $$;

-- 7b. frame_alignment → evaluation.method_fit (we keep your columns)
CREATE OR REPLACE FUNCTION eval_frame_alignment_v0(p_id BIGINT)
RETURNS DOUBLE PRECISION LANGUAGE plpgsql AS $$
DECLARE
  s TEXT; f_id INT; r_code TEXT; sc DOUBLE PRECISION := 0.5;
BEGIN
  SELECT statement, frame_id INTO s, f_id FROM public.posit WHERE id = p_id;
  IF s IS NULL OR f_id IS NULL THEN
    INSERT INTO public.evaluation(posit_id, method_fit, created_at, notes)
    VALUES (p_id, 0.0, now(), 'missing frame');
    RETURN 0.0;
  END IF;

  SELECT rt.code INTO r_code
  FROM public.frame f JOIN public.root_truth rt ON rt.id=f.root_id
  WHERE f.id=f_id;

  IF r_code='jc' THEN
    sc := 0.5
       + 0.1 * (s ~* '\btruth|law|sin|repent|mercy|justice|covenant|obedien|humilit|sanct|sacred\b')::int
       + 0.1 * (s ~* '\bGod|Christ|Lord|Creator\b')::int
       - 0.1 * (s ~* '\bnihil|absurd|self-authored|relative\b')::int;
  ELSIF r_code='sh' THEN
    sc := 0.5
       + 0.1 * (s ~* '\bautonomy|consensus|rights|progress|science|reason|human\b')::int
       - 0.1 * (s ~* '\bdivine|revelation|obedien|sin|sacred\b')::int;
  ELSIF r_code='is' THEN
    sc := 0.5
       + 0.1 * (s ~* '\bsubmission|deen|sharia|ummah|command\b')::int;
  ELSIF r_code='ed' THEN
    sc := 0.5
       + 0.1 * (s ~* '\bemptiness|non-dual|detachment|nirvana|maya\b')::int;
  END IF;

  sc := GREATEST(0, LEAST(1, sc));
  INSERT INTO public.evaluation(posit_id, method_fit, created_at, notes)
  VALUES (p_id, sc, now(), 'frame_alignment v0');
  RETURN sc;
END $$;

-- 7c. cross_frame resonance (use curvature touching posit.frame_id) → evaluation.consensus
CREATE OR REPLACE FUNCTION eval_cross_frame_v0(p_id BIGINT)
RETURNS DOUBLE PRECISION LANGUAGE plpgsql AS $$
DECLARE f_id INT; sc DOUBLE PRECISION := 0.5;
BEGIN
  SELECT frame_id INTO f_id FROM public.posit WHERE id = p_id;
  IF f_id IS NULL THEN
    INSERT INTO public.evaluation(posit_id, consensus, created_at, notes)
    VALUES (p_id, 0.0, now(), 'missing frame');
    RETURN 0.0;
  END IF;

  SELECT COALESCE(AVG(weight),0.0) INTO sc
  FROM public.curvature_multi
  WHERE frame_a = f_id OR frame_b = f_id;

  sc := 0.4 + 0.55 * LEAST(1.0, sc / 0.75);
  INSERT INTO public.evaluation(posit_id, consensus, created_at, notes)
  VALUES (p_id, sc, now(), 'curvature resonance v0');
  RETURN sc;
END $$;

-- 7d. master wrapper: fills coherence, method_fit, consensus and sets confidence + verdict heuristics
CREATE OR REPLACE FUNCTION evaluate_posit_v0(p_id BIGINT)
RETURNS DOUBLE PRECISION LANGUAGE plpgsql AS $$
DECLARE a DOUBLE PRECISION; b DOUBLE PRECISION; c DOUBLE PRECISION; conf DOUBLE PRECISION;
BEGIN
  a := eval_logical_integrity_v0(p_id);
  b := eval_frame_alignment_v0(p_id);
  c := eval_cross_frame_v0(p_id);

  conf := (a + b + c)/3.0;
  -- upsert latest aggregate row into evaluation with confidence & verdict
  INSERT INTO public.evaluation(posit_id, confidence, verdict, created_at, notes)
  VALUES (p_id, conf, CASE
           WHEN conf >= 0.8 THEN 'strong'
           WHEN conf >= 0.6 THEN 'moderate'
           WHEN conf >= 0.4 THEN 'weak'
           ELSE 'poor'
         END, now(), 'evaluate_posit_v0 aggregate')
  ON CONFLICT DO NOTHING;

  RETURN conf;
END $$;

