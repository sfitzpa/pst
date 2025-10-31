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