CREATE TABLE IF NOT EXISTS retrieval_traces (
  retrieval_trace_id TEXT PRIMARY KEY,
  query_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  query_text_hash TEXT,
  query_intent TEXT,
  query_embedding_hash TEXT,
  candidate_fact_ids_json TEXT NOT NULL,
  selected_fact_ids_json TEXT NOT NULL,
  removed_by_privacy_json TEXT,
  rerank_scores_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_traces_query_id
  ON retrieval_traces(query_id);

CREATE INDEX IF NOT EXISTS idx_retrieval_traces_trace_id
  ON retrieval_traces(trace_id);

CREATE TABLE IF NOT EXISTS guardrail_events (
  guardrail_event_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  query_id TEXT,
  fact_id TEXT,
  guardrail_name TEXT NOT NULL,
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  sanitized_payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guardrail_events_trace_id
  ON guardrail_events(trace_id);

CREATE INDEX IF NOT EXISTS idx_guardrail_events_query_id
  ON guardrail_events(query_id);
