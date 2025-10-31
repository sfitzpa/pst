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