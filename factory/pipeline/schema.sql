PRAGMA foreign_keys = ON;

-- One row per sellable pack. spec_hash changes when the YAML, generators, or gates change -> rebuild.
CREATE TABLE IF NOT EXISTS packs (
  pack_id       TEXT PRIMARY KEY,
  category      TEXT NOT NULL CHECK (category IN ('mesh','audio','vfx','shader','ui','bundle')),
  spec_path     TEXT NOT NULL,
  spec_hash     TEXT NOT NULL,
  engine_target TEXT,                      -- e.g. 'godot-4.5'
  created_at    TEXT DEFAULT (datetime('now'))
);

-- Every license any input or tool output can carry. The report/package steps refuse
-- anything whose provenance points at commercial_ok = 0.
CREATE TABLE IF NOT EXISTS licenses (
  license_id        TEXT PRIMARY KEY,      -- 'own-work', 'mit', 'apache-2.0', 'stability-community', 'meshy-paid', 'tripo-paid'
  commercial_ok     INTEGER NOT NULL CHECK (commercial_ok IN (0,1)),
  needs_attribution INTEGER NOT NULL DEFAULT 0,
  conditions        TEXT,                  -- 'under $1M revenue + registered', 'paid plan active at generation time'
  source_url        TEXT,
  text_sha256       TEXT,                  -- hash of the license text you read, so drift is detectable
  checked_on        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
  asset_id      TEXT PRIMARY KEY,          -- '<pack_id>/<name>'
  pack_id       TEXT NOT NULL REFERENCES packs(pack_id),
  kind          TEXT NOT NULL,             -- 'ui_sfx', 'shader', 'particle_scene', 'inbox_mesh', 'ui_panel' ...
  name          TEXT NOT NULL,
  params_json   TEXT NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','passed','failed','rejected','approved')),
  attempts      INTEGER NOT NULL DEFAULT 0,
  output_path   TEXT,
  output_sha256 TEXT,
  run_id        TEXT,                      -- the build that produced the current output
  updated_at    TEXT DEFAULT (datetime('now'))
);

-- Where every byte came from. This table *is* your AI-disclosure text.
CREATE TABLE IF NOT EXISTS provenance (
  asset_id      TEXT NOT NULL REFERENCES assets(asset_id),
  run_id        TEXT NOT NULL,             -- one per build of one asset; only the current run's rows count
  step          TEXT NOT NULL,             -- 'synth', 'generate', 'record', 'retopo', 'bake'
  tool          TEXT NOT NULL,             -- 'factory.sfx_ui', '3dgenstudio', 'tripo-api', 'blender'
  tool_version  TEXT,
  model         TEXT,
  model_version TEXT,
  seed          INTEGER,
  prompt_sha256 TEXT,
  service_plan  TEXT,                      -- 'tripo-pro' etc. Rights depend on the plan *at generation time*
  license_id    TEXT NOT NULL REFERENCES licenses(license_id),
  ai_generated  INTEGER NOT NULL CHECK (ai_generated IN (0,1)),
  cost_usd      REAL DEFAULT 0,
  external_ref  TEXT,                      -- API task id, invoice id, recording session
  output_sha256 TEXT,                      -- the file this run produced
  created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gate_results (
  asset_id   TEXT NOT NULL REFERENCES assets(asset_id),
  attempt    INTEGER NOT NULL,
  recipe     TEXT NOT NULL,                -- packs.spec_hash at the time: old results never leak into reports
  gate       TEXT NOT NULL,
  passed     INTEGER NOT NULL CHECK (passed IN (0,1)),
  measured   TEXT,
  expected   TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_assets_pack_status ON assets(pack_id, status);
CREATE INDEX IF NOT EXISTS ix_gates_asset ON gate_results(asset_id, attempt);

-- License problems in the files you would actually ship (older attempts don't count).
CREATE VIEW IF NOT EXISTS v_license_blockers AS
  SELECT p.asset_id, p.step, p.tool, p.license_id
  FROM provenance p
  JOIN assets a ON a.asset_id = p.asset_id AND a.run_id = p.run_id
  JOIN licenses l ON l.license_id = p.license_id
  WHERE l.commercial_ok = 0 AND a.status != 'rejected';

CREATE VIEW IF NOT EXISTS v_pack_cost AS
  SELECT a.pack_id, COUNT(DISTINCT a.asset_id) AS assets, ROUND(COALESCE(SUM(p.cost_usd),0),2) AS usd
  FROM assets a LEFT JOIN provenance p USING (asset_id)
  GROUP BY a.pack_id;

-- One row per butler push that succeeded. spec_hash = the recipe whose gate results were shipped.
CREATE TABLE IF NOT EXISTS releases (
  pack_id TEXT NOT NULL REFERENCES packs(pack_id), channel TEXT NOT NULL, target TEXT NOT NULL,
  file_sha256 TEXT NOT NULL, butler_build TEXT, spec_hash TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')));
