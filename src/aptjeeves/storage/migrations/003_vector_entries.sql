CREATE TABLE IF NOT EXISTS vector_entries (
  vector_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL,
  fact_type TEXT NOT NULL,
  fact_version INTEGER NOT NULL,
  embedding_text TEXT NOT NULL,
  embedding_hash TEXT NOT NULL,
  embedding_model_version TEXT NOT NULL,
  embedding_json TEXT NOT NULL,
  vector_store_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY (fact_id) REFERENCES canonical_facts(fact_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vector_entries_fact_id_active
  ON vector_entries(fact_id)
  WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_vector_entries_fact_id
  ON vector_entries(fact_id);

CREATE INDEX IF NOT EXISTS idx_vector_entries_status
  ON vector_entries(status);
