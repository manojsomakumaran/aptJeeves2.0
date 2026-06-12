CREATE TABLE IF NOT EXISTS query_runs (
  query_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  status TEXT NOT NULL,
  query_text_redacted TEXT NOT NULL,
  query_text_hash TEXT NOT NULL,
  query_intent TEXT,
  answerer_version TEXT,
  guardrail_version TEXT,
  retrieval_trace_id TEXT,
  final_action TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_query_runs_trace_id
  ON query_runs(trace_id);

CREATE INDEX IF NOT EXISTS idx_query_runs_status
  ON query_runs(status);