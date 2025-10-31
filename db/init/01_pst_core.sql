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