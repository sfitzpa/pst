# PST + EE Initialization Blueprint (Single‑Pi v0.1)

This is the working playbook for bringing up **Predictive Semantic Trajectories (PST)** + the **Epistemology Engine (EE)** on **one Raspberry Pi 5**. It’s opinionated, copy‑paste ready, and sized for your current stack.

> **Assumptions**
>
> * Pi hostname: `pi-core`
> * PST API on `:8090`
> * PST Postgres exposed on host `:5532` (internal container port `5432`)
> * Containers: `pst-api`, `pst-postgres`, `pst-worker`
> * DB name/user/pass for PST: `pst / pst / pstpass`

---

## 1) Database Setup (SQL)

Run these against your PST database (container `pst-postgres`, db `pst`).

### 1.1 Core PST tables

```sql
-- Vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Concepts: base semantic nodes (R1 embeddings)
CREATE TABLE IF NOT EXISTS concept (
  id         BIGSERIAL PRIMARY KEY,
  key        TEXT UNIQUE NOT NULL,
  label      TEXT,
  embedding  vector(1536),          -- you can ALTER to vector(384) later
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Observations: raw sequences per session (provenance)
CREATE TABLE IF NOT EXISTS observation (
  id         BIGSERIAL PRIMARY KEY,
  session_id TEXT,
  seq        INT,
  concept_id BIGINT REFERENCES concept(id),
  outcome    TEXT,
  at         TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS obs_session_seq_idx ON observation (session_id, seq);

-- Trajectories: R2 (first derivative of meaning)
CREATE TABLE IF NOT EXISTS trajectory (
  id         BIGSERIAL PRIMARY KEY,
  source_id  BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
  target_id  BIGINT NOT NULL REFERENCES concept(id) ON DELETE CASCADE,
  delta      vector(1536),          -- E(target) - E(source)
  weight     DOUBLE PRECISION DEFAULT 0.0,
  freq       INTEGER DEFAULT 0,
  last_seen  TIMESTAMPTZ DEFAULT now(),
  context    JSONB
);
CREATE INDEX IF NOT EXISTS traj_source_idx ON trajectory (source_id);
CREATE INDEX IF NOT EXISTS traj_target_idx ON trajectory (target_id);
CREATE INDEX IF NOT EXISTS traj_delta_ivf ON trajectory USING ivfflat (delta vector_l2_ops) WITH (lists = 100);

-- Optional ring registry (R1/R2/R3 bookkeeping)
CREATE TABLE IF NOT EXISTS ring (
  id        SMALLSERIAL PRIMARY KEY,
  name      TEXT UNIQUE NOT NULL,
  order_idx INT NOT NULL,
  operator  TEXT
);
INSERT INTO ring (name, order_idx, operator)
  VALUES ('R1-base',1,'identity')
  ON CONFLICT (name) DO NOTHING;
INSERT INTO ring (name, order_idx, operator)
  VALUES ('R2-delta',2,'delta')
  ON CONFLICT (name) DO NOTHING;
INSERT INTO ring (name, order_idx, operator)
  VALUES ('R3-curvature',3,'delta-of-delta')
  ON CONFLICT (name) DO NOTHING;
```

### 1.2 R3 curvature (derived table)

```sql
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
```

### 1.3 Truth tables (Epistemology core you already have)

```sql
-- Truths with lineage
CREATE TABLE IF NOT EXISTS truth (
  id          BIGSERIAL PRIMARY KEY,
  claim       TEXT NOT NULL,
  method      TEXT,
  evidence    JSONB,
  confidence  DOUBLE PRECISION,
  source      TEXT,
  posit_id    BIGINT, -- to be linked after posit table exists
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS truth_lineage (
  id            BIGSERIAL PRIMARY KEY,
  child_truth   BIGINT REFERENCES truth(id) ON DELETE CASCADE,
  parent_truth  BIGINT REFERENCES truth(id) ON DELETE CASCADE,
  relation      TEXT
);
```

### 1.4 Epistemology Engine (Posits & Evaluation)

```sql
CREATE TABLE IF NOT EXISTS persona (
  id BIGSERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  stance JSONB
);

CREATE TABLE IF NOT EXISTS posit (
  id BIGSERIAL PRIMARY KEY,
  author_id BIGINT REFERENCES persona(id),
  statement TEXT NOT NULL,
  domain TEXT,
  kind TEXT,
  status TEXT DEFAULT 'pinned',      -- pinned|active|under_review|withdrawn
  method_pref JSONB,                 -- ["revelation","reason","observation","testimony"]
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS posit_query (
  id BIGSERIAL PRIMARY KEY,
  posit_id BIGINT REFERENCES posit(id) ON DELETE CASCADE,
  prompt TEXT NOT NULL,
  kind TEXT,
  state TEXT DEFAULT 'open',         -- open|answered|blocked
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence (
  id BIGSERIAL PRIMARY KEY,
  posit_id BIGINT REFERENCES posit(id) ON DELETE CASCADE,
  source TEXT,
  excerpt TEXT,
  method TEXT,
  weight DOUBLE PRECISION,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS challenge (
  id BIGSERIAL PRIMARY KEY,
  posit_id BIGINT REFERENCES posit(id) ON DELETE CASCADE,
  challenger TEXT,
  claim TEXT,
  severity INT DEFAULT 1,
  state TEXT DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS evaluation (
  id BIGSERIAL PRIMARY KEY,
  posit_id BIGINT REFERENCES posit(id) ON DELETE CASCADE,
  coherence NUMERIC,
  correspondence NUMERIC,
  consensus NUMERIC,
  method_fit NUMERIC,
  confidence NUMERIC,
  verdict TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Backlink truth → posit now that posit exists
ALTER TABLE truth
  ADD COLUMN IF NOT EXISTS posit_id BIGINT REFERENCES posit(id);
```

---

## 2) API Endpoints (checklist & minimal contracts)

> Implement as FastAPI routes in `pst-api`. Keep bodies small and composable.

* `POST /concepts` → upsert concept `{key,label,embedding}`
* `POST /observe` → ingest a sequence `{session_id, sequence:[keys...]}` and **update R2**
* `GET /predict/next/{key}?k=5` → ranked next targets from R2
* `GET /plan?start=K&depth=2&k=1` → greedy k-step route (for harness)
* `POST /ingest_line` → `{domain,text,session_id}` → heuristic motif tagging → store R2 with `context.domain`
* `POST /posit` → create posit (pin)
* `POST /posit/{id}/evidence` → attach evidence
* `POST /posit/{id}/evaluate` → run evaluator; may insert `truth`
* `GET  /truth/from_posit/{id}` → return linked truth if promoted

> Add permissive CORS once for Swagger UI:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

---

## 3) Worker Jobs (cron‑style loops)

### 3.1 PST Weight/Decay (hourly)

* **Decay**: `freq *= exp(-(now-last_seen)/half_life)`
* **Weight**: `weight = 1 - exp(-alpha*freq)`

SQL for ad‑hoc recompute:

```sql
UPDATE trajectory SET weight = 1 - exp(-0.15 * freq);
```

### 3.2 EE Evaluator (every 15–60 min)

* Compute `coherence`, `correspondence`, `method_fit`, `consensus` → `confidence`
* Write `evaluation` row; if `confidence >= 0.75` and no severe open challenge → **promote** (insert `truth` with `posit_id`)

---

## 4) Rules (initial set)

### Rule A: Question Battery on Pin

On `POST /posit`, insert standard `posit_query` rows:

* falsifiability, provenance, scope, coherence.

### Rule B: Cross‑Domain Conservation (Handey ↔ Proverbs)

R2 alignment (pair key `A→B`) across `context.domain='handey'` and `'proverbs'` with thresholds → insert `truth` describing conserved transition.

```sql
WITH r2 AS (
  SELECT c1.key||'→'||c2.key AS pair, (t.context->>'domain') AS domain, t.freq, t.weight
  FROM trajectory t
  JOIN concept c1 ON c1.id=t.source_id
  JOIN concept c2 ON c2.id=t.target_id
), agg AS (
  SELECT pair,
         MAX(CASE WHEN domain='handey' THEN weight ELSE 0 END) w_h,
         MAX(CASE WHEN domain='proverbs' THEN weight ELSE 0 END) w_p,
         MAX(CASE WHEN domain='handey' THEN freq ELSE 0 END) f_h,
         MAX(CASE WHEN domain='proverbs' THEN freq ELSE 0 END) f_p
  FROM r2 GROUP BY pair
)
INSERT INTO truth (claim, method, evidence, confidence, source)
SELECT 'Motif transition '||pair||' is conserved across Handey and Proverbs',
       'cross-domain empirical alignment',
       jsonb_build_object('f_handey',f_h,'f_proverbs',f_p,'w_handey',w_h,'w_proverbs',w_p),
       0.5 + 0.5 * LEAST(w_h,w_p),
       'PST EE Auto-Promoter'
FROM agg
WHERE w_h >= 0.5 AND w_p >= 0.5 AND f_h >= 3 AND f_p >= 3
ON CONFLICT DO NOTHING;
```

### Rule C: Curvature Promotion (R3)

Use `curvature` table with triplet key `A→B→C` per domain; if both domains exceed thresholds, promote *curvature truth*.

---

## 5) Ingest: Handey & Proverbs (motif heuristic)

Minimal heuristic (edit later) to tag lines and write R2 with domain tag.

```python
# api/motifs.py
import re, json
MOTIFS = ["setup","inversion","self_denigration","parallelism","contrast","admonition","consequence"]

def motifs_for(text:str, domain:str):
    t = text.lower().strip()
    seq = []
    if re.search(r"\b(but|yet|however)\b", t):
        seq.append("contrast")
    if re.search(r"\b(better .* than|do not|^do\b)\b", t):
        seq.append("admonition")
    if re.search(r"\btherefore|so that|leads to|reap\b", t):
        seq.append("consequence")
    if re.search(r"\bi (am|was|feel|guess|probably|maybe)\b", t) and re.search(r"(dumb|fool|idiot|stupid|pathetic)", t):
        seq.append("self_denigration")
    if re.search(r"(maybe|probably|turns out|then i realized)", t):
        seq.append("inversion")
    if re.search(r".+[,;:]\s*\w.+[,;:]\s*\w", t) or re.search(r"\b(wise|fool|righteous|wicked)\b.*\b(wise|fool|righteous|wicked)\b", t):
        seq.append("parallelism")
    if not seq or seq[0] != "setup":
        seq = ["setup"] + seq
    return seq[:3], {"domain": domain}
```

Endpoint (sketch):

```python
# POST /ingest_line {domain,text,session_id}
# - upserts motifs as concepts (placeholder embeddings ok)
# - writes observation rows
# - updates/creates trajectory edges with live weight and context.domain
```

---

## 6) Planner Endpoint (for the Harness)

Greedy one‑path plan; expand later to k‑best.

```python
# GET /plan?start=setup&depth=2&k=1
# returns [{"path":["setup","contrast","consequence"],"confidence":0.74}]
```

---

## 7) Test Harness (A/B: baseline vs PST)

**Tree**

```
~/harness/
  config.yaml
  cases/
    001_handey.json
    002_proverbs.json
  run_baseline.py
  run_pst.py
  score.py
  out/runs_YYYYMMDD_HHMM/
```

**Case example** (`cases/001_handey.json`)

```json
{
  "id": "001_handey",
  "input": "Write a two-sentence Jack Handey-style quip about losing your keys.",
  "expected_path": ["setup","inversion","self_denigration"],
  "keywords": ["lost my keys","maybe","i guess"]
}
```

**Metrics captured**

* latency_ms, tokens_in, tokens_out
* route_adherence (0/1 via simple keyword checks per motif)
* corrections_needed, accept_human (manual Y/N)

---

## 8) One‑Pi Deployment Notes

* Keep EE tables in **same DB** for v0.1 (split to a second Pi later).
* Log tails:

  * `docker logs -f pst-api`
  * `docker logs -f pst-worker`
* Recompute weights on demand:

  * `UPDATE trajectory SET weight = 1 - exp(-0.15 * freq);`
* Pretty JSON without `jq`:

  * `... | python3 -m json.tool`

---

## 9) First-Light Script (sanity path)

1. Register 3 motifs as concepts (setup/contrast/consequence).
2. `POST /ingest_line` with a Proverbs paraphrase containing a "but" clause.
3. `GET /predict/next/setup` → should surface `contrast`.
4. Build `curvature` table; query top arcs by domain.
5. Insert one **posit** and run `evaluate` → write a **truth** row.

---

## 10) Roadmap (near term)

* Add `/truth/for/trajectory?source=...&target=...` for “why” lookups.
* Add R3 alignment rule (triplet `A→B→C`) for Handey↔Proverbs.
* Introduce `channel` to `trajectory.context` for multi‑channel R2 (syntax/rhetoric/imagery/moral).
* Wire harness to output `metrics.csv` and plot a small trend over time.

> **Definition of Done (v0.1)**
>
> * PST R2 works; R3 materializes.
> * EE tables accept posits, evidence, evaluation; truths can be promoted.
> * `/plan` drives a measured improvement over baseline in at least one case.
> * All steps reproducible from this document.
