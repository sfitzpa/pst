-- Frame Registry schema
CREATE TABLE IF NOT EXISTS root_truth (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT
);

CREATE TABLE IF NOT EXISTS frame (
  id SERIAL PRIMARY KEY,
  root_id INT REFERENCES root_truth(id) ON DELETE CASCADE,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  dimension TEXT,                -- early, late, modern, etc.
  language TEXT,                 -- en, gr, ar, sa...
  moral_axis JSONB DEFAULT '{}'::jsonb,  -- e.g. {"justice":0.8,"mercy":0.6}
  notes TEXT
);

-- Link frames to data
ALTER TABLE move ADD COLUMN IF NOT EXISTS frame_id INT REFERENCES frame(id);
ALTER TABLE move_edge ADD COLUMN IF NOT EXISTS frame_id INT REFERENCES frame(id);
ALTER TABLE curvature_multi ADD COLUMN IF NOT EXISTS frame_a INT REFERENCES frame(id);
ALTER TABLE curvature_multi ADD COLUMN IF NOT EXISTS frame_b INT REFERENCES frame(id);
ALTER TABLE truth ADD COLUMN IF NOT EXISTS frame_pair TEXT;  -- shorthand "proverbs↔handey"
